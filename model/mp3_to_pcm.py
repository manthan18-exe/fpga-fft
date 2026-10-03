
#!/usr/bin/env python3
"""
mp3_to_pcm.py - decode an MP3 into the exact int16 stream the FPGA will receive,
and write every file the later stages need (UART sender, testbenches, golden checks).
 
Usage (run from fpga-fft/model):
    python mp3_to_pcm.py song.mp3
    python mp3_to_pcm.py song.mp3 --plot
 
Needs: ffmpeg on PATH, and `pip install numpy matplotlib`.
Output: vectors/hann_q15.mem  and  vectors/<mp3 name>/...
"""
import argparse
import pathlib
import subprocess
import sys
import wave
 
import numpy as np
 
FS, N = 48000, 1024
BANDS = [(1, 5), (6, 42), (43, 127), (128, 426)]          # inclusive bin ranges
BAND_NAMES = ["bass", "low-mid", "mid-high", "treble"]
HANN_Q15 = np.minimum(
    np.round(0.5 * (1 - np.cos(2 * np.pi * np.arange(N) / N)) * 32768), 32767
).astype(np.int64)                                         # periodic Hann, Q1.15
 
 
def decode(path):
    """MP3 -> int16 mono @ 48 kHz (little-endian) using ffmpeg."""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(FS),
           "-f", "s16le", "-acodec", "pcm_s16le", "-"]
    try:
        res = subprocess.run(cmd, capture_output=True)
    except FileNotFoundError:
        sys.exit("ffmpeg not found. Install it and check that `ffmpeg -version` works in this terminal.")
    if res.returncode != 0:
        sys.exit("ffmpeg failed:\n" + res.stderr.decode(errors="replace"))
    return np.frombuffer(res.stdout, dtype="<i2")
 
 
def window_q15(frame):
    """Hann window in Q1.15 with rounding - what the FPGA multiplier stage must reproduce."""
    return ((frame.astype(np.int64) * HANN_Q15 + (1 << 14)) >> 15).astype(np.int16)
 
 
def analyze(frame):
    """Golden model: window -> FFT scaled by 1/N -> power. Returns (peak_bin, power[512])."""
    xw = window_q15(frame)
    X = np.fft.fft(xw.astype(float))[:512] / N
    p = np.round(X.real) ** 2 + np.round(X.imag) ** 2
    return 1 + int(np.argmax(p[1:])), p                    # DC (bin 0) is skipped
 
 
def save_hex(path, values, digits):
    """One two's-complement hex word per line, for $readmemh."""
    mask = (1 << (4 * digits)) - 1
    np.savetxt(path, np.asarray(values).astype(np.int64) & mask, fmt=f"%0{digits}x")
 
 
def main():
    ap = argparse.ArgumentParser(description="Decode an MP3 into FPGA-ready PCM frames and test vectors.")
    ap.add_argument("mp3")
    ap.add_argument("--out", default="vectors", help="root output folder (default: vectors)")
    ap.add_argument("--plot", action="store_true", help="show a spectrogram of the first 20 s")
    args = ap.parse_args()
 
    src = pathlib.Path(args.mp3)
    if not src.is_file():
        sys.exit(f"File not found: {src}")
    root = pathlib.Path(args.out)
    out = root / src.stem                                   # one folder per input file
    out.mkdir(parents=True, exist_ok=True)
 
    pcm = decode(str(src))
    nfr = len(pcm) // N                                     # the partial last frame is dropped
    if nfr == 0:
        sys.exit("Audio is shorter than one 1024-sample frame.")
    fr = pcm[:nfr * N].reshape(nfr, N)
 
    a = np.abs(pcm.astype(np.int64))
    print(f"samples {len(pcm)}  duration {len(pcm) / FS:.2f}s  frames {nfr}")
    print(f"peak {a.max()}  rms {np.sqrt((pcm.astype(float) ** 2).mean()):.0f}  "
          f"dc {pcm.mean():.1f}  clipped {(a >= 32767).sum()}")
 
    # --- files for the next stages -------------------------------------------------
    np.save(out / "pcm_48k_mono.npy", pcm)                  # golden model / compare script
    fr.tofile(out / "pcm_48k_mono.bin")                     # raw int16 LE for the UART sender
    with wave.open(str(out / "decoded.wav"), "wb") as w:    # listening check
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(pcm.tobytes())
    save_hex(root / "hann_q15.mem", HANN_Q15, 4)            # Hann ROM for the FPGA
 
    # --- three representative frames as simulation vectors ----------------------------
    rms = np.sqrt((fr.astype(float) ** 2).mean(axis=1))
    picks = {"loud": int(rms.argmax()),
             "quiet": int(np.where(rms > 50, rms, np.inf).argmin()),
             "mid": nfr // 2}
    print()
    for name, i in picks.items():
        f = fr[i]
        pk, p = analyze(f)
        save_hex(out / f"frame_{name}.hex", f, 4)                   # input to the Hann stage
        save_hex(out / f"frame_{name}_win.hex", window_q15(f), 4)   # expected Hann output
        save_hex(out / f"frame_{name}_pow.hex", p, 8)               # expected |X|^2, bins 0..511
        bands = [int(p[lo:hi + 1].sum()) for lo, hi in BANDS]
        print(f"{name:5s} frame {i:5d}: peak bin {pk} = {pk * FS / N:.1f} Hz | " +
              "  ".join(f"{n} {b:.3g}" for n, b in zip(BAND_NAMES, bands)))
 
    # --- bins around the peak of the loud frame (amplitude sanity check) --------------
    pk, p = analyze(fr[picks["loud"]])
    print("\nbins around the peak (loud frame):")
    for k in range(max(1, pk - 3), min(511, pk + 3) + 1):
        print(f"  bin {k:3d}  {k * FS / N:8.1f} Hz  mag {np.sqrt(p[k]):9.1f}")
    print(f"\nfiles written to {out}")
 
    if args.plot:
        import matplotlib.pyplot as plt
        plt.specgram(pcm[:FS * 20] / 32768, NFFT=N, Fs=FS, noverlap=0, window=np.hanning(N))
        plt.ylim(0, 20000)
        plt.xlabel("time (s)")
        plt.ylabel("frequency (Hz)")
        plt.title(src.name)
        plt.show()
 
 
if __name__ == "__main__":
    main()