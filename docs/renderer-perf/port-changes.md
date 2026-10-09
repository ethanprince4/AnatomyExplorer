# wgpu port: known differences from the OpenGL renderer

Every place where the wgpu renderer's picture can differ from today's OpenGL renderer, with the reason and size.
Sizes are in 1/255 of the final 8-bit image unless stated. "Same GPU" means GL and wgpu both on the RTX 3080.

| Area | Difference | Size | Why it is accepted |
|---|---|---|---|
| Textured parts, anisotropic filtering (8x) | GL and Vulkan/Metal drivers implement anisotropic filtering differently | same GPU: mean 1.2, max 201 at grazing angles; with anisotropy off on both sides: mean 0.01, max 2.2 | Driver sampler behaviour, not our code; the same texture through plain WGSL `textureSample` shows the same gap. On a Mac both GL (layered on Metal) and wgpu use Apple's sampler. |
| Stripe pattern next to a cut plane | `MAIN_FS` discards clipped fragments before its `fwidth`, so GL's derivative there is undefined; wgpu computes it analytically | same GPU: up to 55 on a few stripe pixels beside the cut | GL's value is undefined behaviour (a latent bug in `app/viewer/shaders.py`); wgpu gives the intended result. |
| Noise ("mottle") across GPU vendors | `fract(sin(x) * 43758.5)` hashes depend on each vendor's `sin` precision | NVIDIA vs Intel: a different random pattern on noise-textured parts (mean about 27 on those parts only) | Same between GL and wgpu on one GPU; GL itself differs the same way between vendors. Re-check on a Mac (Metal fast-math `sin`). |
| Selection outlines at 1.5 px width across vendors | outline taps landing exactly on texel boundaries round differently | NVIDIA vs Intel: up to 77 on 0.05-0.13% of pixels | Same between GL and wgpu on one GPU (bit-identical on NVIDIA). |
| SSAO | single-sample threshold flips from floating-point arithmetic order | same GPU: 19 of 921,600 pixels before blur; after blur max 3, mean 0.004 | Arithmetic noise; reduced from 716 pixels by matching the driver's fused multiply-add. |
