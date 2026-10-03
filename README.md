# fpga-fft: FPGA audio spectrum analyzer

MP3 -> PCM (48 kHz / 16-bit / mono) on the laptop -> UART (2 Mbaud) -> Arty A7-35T:
Hann window -> 1024-point FFT -> power -> peak and band energy -> AXI -> MicroBlaze -> results back to the laptop.

## Status
- [x] MP3 -> PCM decode and golden-model test vectors (`model/`)
- [ ] Vivado project, UART link, DSP chain, MicroBlaze, laptop receiver

## Regenerate the test data (needs ffmpeg, numpy)

    cd model
    ffmpeg -f lavfi -i "sine=frequency=1500:sample_rate=48000:duration=10" -ac 1 -b:a 192k tone1500.mp3
    python mp3_to_pcm.py tone1500.mp3

Expected for tone1500: peak bin 32, bins 31/32/33 magnitudes 497 / 993 / 497.
