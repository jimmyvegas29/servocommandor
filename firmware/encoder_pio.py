"""X4 quadrature decoder that lives entirely in the PIO: no interrupts, no
Python in the counting path, so nothing on the CPU (Bluetooth, UART, GC)
can ever make it miss an edge.

Port of pico-examples/pio/quadrature_encoder: the state machine keeps the
signed count in its Y register, samples both pins every loop (about 12
instructions, roughly 100 ns) and jumps through a 16-entry table indexed
by (old A, old B, new A, new B).  Each loop also pushes the count into the
RX FIFO without blocking, so reading it is just draining the FIFO.

The jump table must sit at instruction address 0.  MicroPython places
programs at the top of free PIO memory, so the program is padded to all 32
instructions, which forces it to offset 0.  One copy of the program serves
both state machines in the PIO block.
"""
import rp2
from machine import Pin


@rp2.asm_pio(in_shiftdir=rp2.PIO.SHIFT_LEFT, out_shiftdir=rp2.PIO.SHIFT_RIGHT)
def _quadrature():
    # 16-entry jump table, index = old_state << 2 | new_state
    jmp("update")        # 00 -> 00
    jmp("decrement")     # 00 -> 01
    jmp("increment")     # 00 -> 10
    jmp("update")        # 00 -> 11 (invalid, both changed)
    jmp("increment")     # 01 -> 00
    jmp("update")        # 01 -> 01
    jmp("update")        # 01 -> 10 (invalid)
    jmp("decrement")     # 01 -> 11
    jmp("decrement")     # 10 -> 00
    jmp("update")        # 10 -> 01 (invalid)
    jmp("update")        # 10 -> 10
    jmp("increment")     # 10 -> 11
    jmp("update")        # 11 -> 00 (invalid)
    jmp("increment")     # 11 -> 01
    jmp("decrement")     # 11 -> 10
    jmp("update")        # 11 -> 11
    label("decrement")
    jmp(y_dec, "update")  # y -= 1 (jmp y-- always falls to update)
    wrap_target()
    label("update")
    mov(isr, y)
    push(noblock)
    out(isr, 2)          # previous 2 pin bits (low bits of OSR) -> ISR
    in_(pins, 2)         # current 2 pin bits appended -> 4-bit table index
    mov(osr, isr)        # remember for next loop
    mov(pc, isr)         # jump into the table
    label("increment")
    mov(y, invert(y))
    jmp(y_dec, "increment_cont")
    label("increment_cont")
    mov(y, invert(y))    # y = ~(~y - 1) = y + 1
    wrap()
    # padding to 32 instructions so the program is loaded at address 0
    nop()
    nop()
    nop()
    nop()
    nop()
    nop()


class Encoder:
    """Drop-in for encoder_rp2.Encoder: Encoder(sm_no, base_pin).value()."""

    def __init__(self, sm_no, base_pin, scale=1):
        self.scale = scale
        self._offset = 0
        self._last = 0
        self.stalled = 0
        self.sm = rp2.StateMachine(sm_no, _quadrature, in_base=base_pin)
        # y = 0, OSR = current pins so the first loop sees "no change"
        self.sm.exec("set(y, 0)")
        self.sm.exec("in_(pins, 2)")
        self.sm.exec("mov(osr, isr)")
        self.sm.exec("mov(isr, null)")
        self.sm.active(1)

    def _raw(self):
        sm = self.sm
        # the state machine refills the 4-deep FIFO every ~100 ns, so the
        # oldest queued value is well under a microsecond old: take it.  Never
        # drain "until empty" (it never empties) and never block (a stalled
        # state machine must not hang the node).
        if not sm.rx_fifo():
            self.stalled += 1
            return self._last
        v = sm.get()
        v = v - 0x100000000 if v & 0x80000000 else v
        self._last = -v
        # the table counts A-leading as negative; the old decoder (and so the
        # panel's saved datums and direction settings) had it positive
        return -v

    def value(self, value=None):
        if value is not None:
            self._offset = value - self._raw()
        return self._raw() + self._offset

    def position(self, value=None):
        if value is not None:
            self.value(round(value / self.scale))
        return self.value() * self.scale
