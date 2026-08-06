    .module sound

    .include "audio_params.s"

    YM_ADDR_1 = 0x04
    YM_DATA_1 = 0x05
    SOUND_CODE = 0x00
    SOUND_REPLY = 0x0c
    NMI_ENABLE = 0x08
    NMI_DISABLE = 0x18

    REG_ADPCM_B_CONTROL = 0x10
    REG_ADPCM_B_PAN = 0x11
    REG_ADPCM_B_START_LO = 0x12
    REG_ADPCM_B_START_HI = 0x13
    REG_ADPCM_B_END_LO = 0x14
    REG_ADPCM_B_END_HI = 0x15
    REG_ADPCM_B_DELTA_LO = 0x19
    REG_ADPCM_B_DELTA_HI = 0x1a
    REG_ADPCM_B_LEVEL = 0x1b

    REG_SSG_MIXER = 0x07
    REG_SSG_LEVEL_A = 0x08
    REG_SSG_LEVEL_B = 0x09
    REG_SSG_LEVEL_C = 0x0a

    CONTROL_RESET = 0x01
    CONTROL_PLAY_LOOPED = 0xb0
    PAN_BOTH = 0xc0
    LEVEL_MAX = 0xff
    SSG_ALL_OFF = 0x3f

    CMD_SHIFT_PAGE = 0x10
    CMD_PLAY = 0x50
    CMD_STOP = 0x60

    PAGE_WORD = 0xf800
    ACK_COUNT = 0xf802

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
    push af
    push bc
    push de
    push hl

    in a, (SOUND_CODE)
    ld d, a
    ld a, (ACK_COUNT)
    inc a
    ld (ACK_COUNT), a
    out (SOUND_REPLY), a
    ld a, d
    and #0x0f
    ld e, a
    ld a, d
    and #0xf0

    cp #CMD_SHIFT_PAGE
    jr z, nmi_shift_page
    cp #CMD_PLAY
    jr z, nmi_play
    cp #CMD_STOP
    jr z, nmi_stop
    jr nmi_done

nmi_shift_page:
    ld hl, (PAGE_WORD)
    add hl, hl
    add hl, hl
    add hl, hl
    add hl, hl
    ld a, e
    or l
    ld l, a
    ld (PAGE_WORD), hl
    jr nmi_done

nmi_play:
    call audio_start
    jr nmi_done

nmi_stop:
    call audio_stop

nmi_done:
    pop hl
    pop de
    pop bc
    pop af
    retn

    .org 0x0100
boot:
    xor a
    out (SOUND_REPLY), a
    in a, (SOUND_CODE)

    ld hl, #0x0000
    ld (PAGE_WORD), hl
    xor a
    ld (ACK_COUNT), a

    out (NMI_ENABLE), a

    call silence_ssg

    ld b, #REG_ADPCM_B_PAN
    ld c, #PAN_BOTH
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

idle:
    halt
    jr idle

silence_ssg:
    ld b, #REG_SSG_MIXER
    ld c, #SSG_ALL_OFF
    call ym_write
    ld b, #REG_SSG_LEVEL_A
    ld c, #0x00
    call ym_write
    ld b, #REG_SSG_LEVEL_B
    ld c, #0x00
    call ym_write
    ld b, #REG_SSG_LEVEL_C
    ld c, #0x00
    jp ym_write

audio_stop:
    ld b, #REG_ADPCM_B_CONTROL
    ld c, #CONTROL_RESET
    jp ym_write

audio_start:
    call audio_stop

    ld a, (PAGE_WORD)
    ld c, a
    ld b, #REG_ADPCM_B_START_LO
    call ym_write
    ld a, (PAGE_WORD + 1)
    ld c, a
    ld b, #REG_ADPCM_B_START_HI
    call ym_write

    ld b, #REG_ADPCM_B_END_LO
    ld c, #ADPCM_B_END_LO
    call ym_write
    ld b, #REG_ADPCM_B_END_HI
    ld c, #ADPCM_B_END_HI
    call ym_write

    ld b, #REG_ADPCM_B_CONTROL
    ld c, #CONTROL_PLAY_LOOPED
    jp ym_write

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
