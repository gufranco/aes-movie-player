    .module sound

    .include "build/generated/audio_params.s"

    YM_ADDR_1 = 0x04
    YM_DATA_1 = 0x05
    SOUND_CODE = 0x00
    SOUND_REPLY = 0x0c

    REG_ADPCM_B_CONTROL = 0x10
    REG_ADPCM_B_PAN = 0x11
    REG_ADPCM_B_START_LO = 0x12
    REG_ADPCM_B_START_HI = 0x13
    REG_ADPCM_B_END_LO = 0x14
    REG_ADPCM_B_END_HI = 0x15
    REG_ADPCM_B_DELTA_LO = 0x19
    REG_ADPCM_B_DELTA_HI = 0x1a
    REG_ADPCM_B_LEVEL = 0x1b

    CONTROL_RESET = 0x01
    CONTROL_PLAY_LOOPED = 0xb0
    PAN_BOTH = 0xc0
    LEVEL_MAX = 0xff

    .area CODE (ABS)

    .org 0x0000
reset_vector:
    di
    im 1
    ld sp, #0xfffc
    jp boot

    .org 0x0038
irq_vector:
    reti

    .org 0x0066
nmi_vector:
    in a, (SOUND_CODE)
    out (SOUND_REPLY), a
    retn

    .org 0x0100
boot:
    xor a
    out (SOUND_REPLY), a
    in a, (SOUND_CODE)

    ld b, #REG_ADPCM_B_CONTROL
    ld c, #CONTROL_RESET
    call ym_write

    ld b, #REG_ADPCM_B_PAN
    ld c, #PAN_BOTH
    call ym_write

    ld b, #REG_ADPCM_B_START_LO
    ld c, #ADPCM_B_START_LO
    call ym_write
    ld b, #REG_ADPCM_B_START_HI
    ld c, #ADPCM_B_START_HI
    call ym_write

    ld b, #REG_ADPCM_B_END_LO
    ld c, #ADPCM_B_END_LO
    call ym_write
    ld b, #REG_ADPCM_B_END_HI
    ld c, #ADPCM_B_END_HI
    call ym_write

    ld b, #REG_ADPCM_B_DELTA_LO
    ld c, #ADPCM_B_DELTA_LO
    call ym_write
    ld b, #REG_ADPCM_B_DELTA_HI
    ld c, #ADPCM_B_DELTA_HI
    call ym_write

    ld b, #REG_ADPCM_B_LEVEL
    ld c, #LEVEL_MAX
    call ym_write

    ld b, #REG_ADPCM_B_CONTROL
    ld c, #CONTROL_PLAY_LOOPED
    call ym_write

idle:
    halt
    jr idle

ym_write:
    call ym_wait_ready
    ld a, b
    out (YM_ADDR_1), a
    call ym_settle
    ld a, c
    out (YM_DATA_1), a
    call ym_settle
    ret

ym_wait_ready:
    in a, (YM_ADDR_1)
    rlca
    jr c, ym_wait_ready
    ret

ym_settle:
    push bc
    ld b, #16
ym_settle_loop:
    djnz ym_settle_loop
    pop bc
    ret
