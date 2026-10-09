# Renderer benchmark: baseline

Settings: 2560x1600 physical px, device pixel ratio 2 (QT_SCREEN_SCALE_FACTORS=2), default user settings, real ModelViewport / Viewport widgets
GPU: 1961/10240 MiB used at start (other agents may share the GPU)
Started: 2026-10-09 08:59:03

## 1. Load (app prepare chain: decode, prepare incl. lod.build, GPU upload)

| model | triangles | vertices | parts | items | LOD parts x levels | B/vertex | decode s | prepare s (excl. decode, LOD) | lod.build s | upload s | peak RSS MB | GPU MiB (upload) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pancreas | 25,164,600 | 15,499,318 | 74 | 74 | 42 x 4 | 76.0 | 2.41 | 1.94 | 3.33 | 0.49 | 4,161 | 1,517 |
| duodenum | 24,596,454 | 14,462,138 | 42 | 42 | 4 x 4 | 76.0 | 2.19 | 2.03 | 0.32 | 0.60 | 3,756 | 1,387 |
| colon_wall | 24,504,286 | 15,239,757 | 43 | 43 | 5 x 4 | 76.0 | 2.25 | 1.90 | 2.38 | 0.53 | 4,031 | 1,497 |
| kidney_nephron | 7,845,955 | 3,925,837 | 267 | 267 | 150 x 4 | 76.0 | 0.79 | 0.70 | 0.98 | 0.14 | 1,218 | 416 |
| jejunum | 7,310,777 | 3,806,287 | 272 | 272 | 4 x 4 | 24.0 | 1.21 | 0.66 | 0.18 | 0.12 | 1,072 | 185 |
| neuron | 6,623,500 | 3,374,521 | 122 | 122 | 100 x 4 | 76.0 | 0.71 | 0.66 | 1.00 | 0.11 | 1,076 | 350 |
| ileum | 6,270,922 | 3,197,617 | 49 | 49 | 1 x 4 | 24.0 | 0.39 | 0.59 | 0.09 | 0.11 | 926 | 154 |
| thin_skin | 5,244,724 | 2,161,887 | 58 | 58 | 4 x 4 | 24.0 | 0.39 | 0.51 | 0.83 | 0.09 | 759 | 126 |
| axillary_skin | 4,634,670 | 2,336,584 | 33 | 33 | 0 x 0 | 24.0 | 0.39 | 0.49 | 0.05 | 0.08 | 702 | 111 |
| whole_heart | 3,769,677 | 1,941,125 | 154 | 154 | 18 x 4 | 76.0 | 0.39 | 0.50 | 0.10 | 0.06 | 677 | 188 |
| ear | 3,459,071 | 1,771,955 | 103 | 103 | 19 x 4 | 24.0 | 0.45 | 0.44 | 0.27 | 0.07 | 556 | 89 |
| male_reproductive | 2,825,590 | 1,415,518 | 92 | 92 | 10 x 4 | 24.0 | 0.25 | 0.40 | 0.13 | 0.06 | 466 | 68 |
| cardiac_muscle | 2,775,990 | 1,417,644 | 257 | 257 | 0 x 0 | 76.0 | 0.32 | 0.44 | 0.08 | 0.05 | 546 | 136 |
| thyroid_parathyroid_review_v2 | 2,609,555 | 1,305,795 | 21 | 21 | 4 x 4 | 76.0 | 0.22 | 0.45 | 0.10 | 0.05 | 517 | 127 |
| ileocecal_rectum | 2,534,292 | 1,271,835 | 47 | 47 | 4 x 4 | 24.0 | 0.23 | 0.39 | 0.15 | 0.05 | 466 | 62 |
| eyeball | 2,523,710 | 1,266,852 | 61 | 61 | 4 x 4 | 76.0 | 0.20 | 0.39 | 0.18 | 0.05 | 509 | 125 |
| female_reproductive | 2,505,452 | 1,255,664 | 137 | 137 | 20 x 4 | 24.0 | 0.23 | 0.38 | 0.15 | 0.05 | 467 | 61 |
| cornea | 2,199,287 | 1,167,860 | 23 | 23 | 0 x 0 | 24.0 | 0.20 | 0.38 | 0.03 | 0.05 | 409 | 53 |
| hepatobiliary | 2,130,921 | 1,075,960 | 55 | 55 | 1 x 4 | 24.0 | 0.19 | 0.38 | 0.05 | 0.04 | 398 | 50 |
| tooth | 2,129,832 | 1,064,888 | 33 | 33 | 2 x 4 | 24.0 | 0.27 | 0.39 | 0.03 | 0.04 | 398 | 49 |
| lymph_node | 2,063,728 | 1,131,322 | 42 | 42 | 0 x 0 | 24.0 | 0.18 | 0.37 | 0.04 | 0.04 | 398 | 50 |
| bladder_wall | 1,990,087 | 1,141,408 | 61 | 61 | 0 x 0 | 24.0 | 0.22 | 0.38 | 0.03 | 0.04 | 397 | 49 |
| tongue_papillae | 1,733,021 | 1,056,131 | 40 | 40 | 5 x 4 | 24.0 | 0.18 | 0.36 | 0.04 | 0.04 | 379 | 44 |
| compact_bone | 1,716,552 | 901,347 | 32 | 32 | 0 x 0 | 24.0 | 0.16 | 0.34 | 0.02 | 0.03 | 362 | 40 |
| thick_skin | 1,451,988 | 1,032,633 | 75 | 75 | 12 x 4 | 24.0 | 0.16 | 0.36 | 0.06 | 0.04 | 375 | 41 |
| muscular_artery | 1,357,110 | 692,808 | 14 | 14 | 0 x 0 | 24.0 | 0.11 | 0.32 | 0.02 | 0.03 | 327 | 30 |
| trachea_wall | 1,322,862 | 877,055 | 38 | 38 | 4 x 4 | 24.0 | 0.13 | 0.34 | 0.03 | 0.03 | 351 | 35 |
| vein_wall | 1,277,152 | 650,385 | 13 | 13 | 0 x 0 | 24.0 | 0.11 | 0.32 | 0.02 | 0.03 | 322 | 28 |
| lung_acinus_review_v2 | 1,255,640 | 735,172 | 28 | 28 | 3 x 4 | 24.0 | 0.12 | 0.34 | 0.02 | 0.03 | 334 | 30 |
| skeletal_muscle | 1,244,600 | 628,496 | 25 | 25 | 4 x 4 | 24.0 | 0.11 | 0.33 | 0.14 | 0.03 | 330 | 32 |
| stomach_wall | 1,223,645 | 620,146 | 26 | 26 | 0 x 0 | 24.0 | 0.09 | 0.33 | 0.02 | 0.03 | 317 | 27 |
| elastic_artery | 1,188,860 | 674,150 | 15 | 15 | 0 x 0 | 24.0 | 0.10 | 0.32 | 0.02 | 0.03 | 324 | 28 |
| liver_lobule | 1,114,022 | 563,527 | 26 | 26 | 0 x 0 | 24.0 | 0.09 | 0.32 | 0.02 | 0.03 | 312 | 24 |
| peripheral_nerve | 736,480 | 386,556 | 16 | 16 | 0 x 0 | 24.0 | 0.06 | 0.29 | 0.01 | 0.02 | 281 | 15 |
| blood_cells | 711,790 | 371,149 | 27 | 27 | 2 x 4 | 24.0 | 0.06 | 0.31 | 0.02 | 0.02 | 280 | 14 |
| oesophagus_wall | 678,785 | 565,464 | 32 | 32 | 0 x 0 | 24.0 | 0.07 | 0.29 | 0.02 | 0.02 | 293 | 19 |
| retina | 630,350 | 316,287 | 28 | 28 | 0 x 0 | 24.0 | 0.06 | 0.29 | 0.01 | 0.02 | 268 | 11 |
| scalp | 528,600 | 280,621 | 165 | 165 | 0 x 0 | 24.0 | 0.07 | 0.30 | 0.01 | 0.02 | 260 | 10 |
| capillary_bed | 516,568 | 331,573 | 36 | 36 | 0 x 0 | 76.0 | 0.06 | 0.30 | 0.02 | 0.01 | 306 | 27 |
| lymph_drainage | 211,769 | 109,706 | 45 | 45 | 9 x 4 | 76.0 | 0.03 | 0.28 | 0.01 | 0.01 | 236 | 9 |
| spleen | 198,384 | 103,590 | 28 | 28 | 2 x 4 | 24.0 | 0.02 | 0.28 | 0.02 | 0.01 | 226 | 3 |

## 2. Frames at 2560x1600, DPR 2 (model viewer; wall ms includes ctx.finish())

| model | settled ms | orbit median ms | orbit p95 | orbit max | CPU submit ms | GPU ms (sum of passes) | draw calls | model draws | geometry passes | Mtri submitted | readbacks/frame | frames w/ shadow pass (of 120) | MSAA |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pancreas | 24.9 | 25.1 | 28.6 | 29.0 | 0.9 | 24.2 | 35 | 30 | 2 | 50.06 | 0 | 0 | 4 |
| duodenum | 31.2 | 28.8 | 31.9 | 33.6 | 1.1 | 28.2 | 30 | 25 | 2 | 49.19 | 0 | 0 | 4 |
| colon_wall | 34.1 | 31.2 | 34.3 | 35.0 | 1.1 | 30.1 | 31 | 26 | 2 | 49.01 | 0 | 0 | 4 |
| kidney_nephron | 8.2 | 7.1 | 8.6 | 9.8 | 1.3 | 5.6 | 55 | 50 | 2 | 5.03 | 0 | 0 | 4 |
| jejunum | 16.6 | 14.3 | 15.8 | 16.1 | 1.4 | 13.0 | 36 | 31 | 2 | 14.62 | 0 | 0 | 4 |
| neuron | 10.8 | 9.5 | 11.0 | 11.6 | 1.3 | 8.0 | 89 | 84 | 2 | 5.06 | 0 | 0 | 4 |
| ileum | 19.7 | 18.0 | 19.7 | 20.3 | 1.1 | 16.7 | 36 | 31 | 2 | 12.54 | 0 | 0 | 4 |
| thin_skin | 14.6 | 13.4 | 15.2 | 18.0 | 1.3 | 12.1 | 60 | 55 | 2 | 1.38 | 0 | 0 | 4 |
| axillary_skin | 22.5 | 20.6 | 22.5 | 23.3 | 1.1 | 19.4 | 38 | 33 | 2 | 9.27 | 0 | 0 | 4 |
| whole_heart | 12.3 | 11.5 | 12.9 | 13.7 | 1.0 | 10.2 | 44 | 39 | 2 | 1.90 | 0 | 0 | 4 |
| ear | 11.2 | 8.2 | 10.3 | 11.6 | 1.7 | 6.6 | 109 | 104 | 2 | 6.64 | 0 | 0 | 4 |
| male_reproductive | 12.9 | 10.6 | 12.2 | 12.5 | 1.8 | 8.8 | 99 | 94 | 2 | 5.20 | 0 | 0 | 4 |
| cardiac_muscle | 11.8 | 10.9 | 11.6 | 12.0 | 0.9 | 9.7 | 7 | 2 | 2 | 5.55 | 0 | 0 | 4 |
| thyroid_parathyroid_review_v2 | 9.2 | 8.0 | 8.5 | 8.6 | 0.8 | 6.9 | 26 | 21 | 2 | 5.22 | 0 | 0 | 4 |
| ileocecal_rectum | 12.5 | 10.6 | 12.4 | 12.9 | 1.1 | 9.4 | 51 | 46 | 2 | 4.45 | 0 | 0 | 4 |
| eyeball | 10.0 | 8.1 | 10.5 | 11.5 | 0.9 | 7.2 | 26 | 21 | 2 | 1.09 | 0 | 0 | 4 |
| female_reproductive | 11.9 | 10.2 | 11.4 | 13.3 | 1.6 | 8.5 | 93 | 88 | 2 | 2.40 | 0 | 0 | 4 |
| cornea | 16.5 | 15.5 | 18.0 | 19.6 | 1.0 | 14.1 | 29 | 24 | 2 | 4.40 | 0 | 0 | 4 |
| hepatobiliary | 13.5 | 11.7 | 13.9 | 15.3 | 1.2 | 10.3 | 42 | 37 | 2 | 4.26 | 0 | 0 | 4 |
| tooth | 10.9 | 8.8 | 11.3 | 12.0 | 0.8 | 7.8 | 27 | 22 | 2 | 3.93 | 0 | 0 | 4 |
| lymph_node | 10.8 | 8.2 | 11.2 | 11.9 | 1.0 | 7.0 | 47 | 42 | 2 | 1.72 | 0 | 0 | 4 |
| bladder_wall | 16.9 | 15.7 | 17.6 | 18.9 | 1.0 | 14.5 | 31 | 26 | 2 | 3.98 | 0 | 0 | 4 |
| tongue_papillae | 29.2 | 21.3 | 28.9 | 31.2 | 1.1 | 20.5 | 38 | 33 | 2 | 3.47 | 0 | 0 | 4 |
| compact_bone | 17.7 | 16.5 | 19.0 | 20.7 | 1.0 | 15.3 | 31 | 26 | 2 | 3.43 | 0 | 0 | 4 |
| thick_skin | 17.2 | 16.7 | 18.4 | 20.6 | 1.4 | 15.0 | 54 | 49 | 2 | 2.81 | 0 | 0 | 4 |
| muscular_artery | 17.5 | 15.8 | 18.1 | 18.8 | 0.9 | 14.9 | 20 | 15 | 2 | 2.71 | 0 | 0 | 4 |
| trachea_wall | 14.3 | 14.0 | 16.7 | 17.4 | 1.0 | 12.8 | 39 | 34 | 2 | 2.60 | 0 | 0 | 4 |
| vein_wall | 17.8 | 16.2 | 18.7 | 19.4 | 0.8 | 15.2 | 18 | 13 | 2 | 2.55 | 0 | 0 | 4 |
| lung_acinus_review_v2 | 9.6 | 8.8 | 10.6 | 11.3 | 0.8 | 8.0 | 25 | 20 | 2 | 2.38 | 0 | 0 | 4 |
| skeletal_muscle | 16.0 | 14.5 | 17.8 | 18.9 | 1.0 | 13.5 | 33 | 28 | 2 | 1.87 | 0 | 0 | 4 |
| stomach_wall | 17.2 | 15.8 | 17.9 | 18.8 | 0.9 | 14.7 | 25 | 20 | 2 | 2.45 | 0 | 0 | 4 |
| elastic_artery | 20.7 | 20.0 | 21.7 | 22.7 | 0.9 | 18.8 | 20 | 15 | 2 | 2.38 | 0 | 0 | 4 |
| liver_lobule | 12.6 | 12.8 | 14.3 | 16.3 | 1.0 | 11.8 | 29 | 24 | 2 | 2.21 | 0 | 0 | 4 |
| peripheral_nerve | 12.5 | 12.8 | 15.6 | 17.0 | 0.9 | 12.0 | 21 | 16 | 2 | 1.47 | 0 | 0 | 4 |
| blood_cells | 5.9 | 5.4 | 6.0 | 6.5 | 1.0 | 4.4 | 31 | 26 | 2 | 1.42 | 0 | 0 | 4 |
| oesophagus_wall | 15.2 | 14.8 | 16.5 | 17.2 | 0.9 | 13.9 | 26 | 21 | 2 | 1.26 | 0 | 0 | 4 |
| retina | 11.2 | 10.2 | 12.1 | 12.6 | 1.0 | 9.0 | 33 | 28 | 2 | 1.20 | 0 | 0 | 4 |
| scalp | 12.9 | 12.1 | 13.7 | 16.4 | 2.2 | 9.9 | 169 | 164 | 2 | 1.00 | 0 | 0 | 4 |
| capillary_bed | 7.5 | 6.6 | 7.6 | 7.8 | 0.7 | 5.7 | 12 | 7 | 2 | 1.03 | 0 | 0 | 4 |
| lymph_drainage | 6.2 | 6.2 | 6.8 | 7.5 | 0.8 | 5.2 | 13 | 8 | 2 | 0.42 | 0 | 0 | 4 |
| spleen | 8.3 | 6.2 | 8.1 | 9.1 | 0.8 | 5.3 | 23 | 18 | 2 | 0.34 | 0 | 0 | 4 |

## 3. GPU ms per pass during the orbit (median over frames)

| model | resolve | start | ao | ao_tmp | main | pre | target |
|---|---|---|---|---|---|---|---|
| pancreas | 0.07 | 0.00 | 1.92 | 0.08 | 16.52 | 5.51 | 0.04 |
| duodenum | 0.07 | 0.00 | 5.35 | 0.18 | 16.51 | 5.59 | 0.04 |
| colon_wall | 0.07 | 0.00 | 4.58 | 0.16 | 19.47 | 5.70 | 0.04 |
| kidney_nephron | 0.07 | 0.00 | 2.07 | 0.09 | 2.70 | 0.50 | 0.04 |
| jejunum | 0.07 | 0.00 | 2.88 | 0.11 | 8.46 | 1.28 | 0.04 |
| neuron | 0.07 | 0.00 | 2.83 | 0.10 | 3.90 | 0.76 | 0.04 |
| ileum | 0.07 | 0.00 | 3.93 | 0.15 | 11.05 | 1.33 | 0.04 |
| thin_skin | 0.07 | 0.00 | 5.66 | 0.17 | 4.88 | 0.81 | 0.04 |
| axillary_skin | 0.08 | 0.00 | 6.41 | 0.19 | 10.60 | 1.74 | 0.05 |
| whole_heart | 0.07 | 0.00 | 5.80 | 0.15 | 3.48 | 0.53 | 0.04 |
| ear | 0.07 | 0.00 | 3.06 | 0.11 | 2.78 | 0.43 | 0.04 |
| male_reproductive | 0.07 | 0.00 | 4.03 | 0.13 | 3.67 | 0.52 | 0.04 |
| cardiac_muscle | 0.07 | 0.00 | 2.96 | 0.12 | 5.79 | 0.78 | 0.04 |
| thyroid_parathyroid_review_v2 | 0.07 | 0.00 | 2.11 | 0.10 | 3.93 | 0.58 | 0.04 |
| ileocecal_rectum | 0.07 | 0.00 | 4.25 | 0.15 | 4.13 | 0.57 | 0.04 |
| eyeball | 0.07 | 0.00 | 4.20 | 0.13 | 2.16 | 0.41 | 0.04 |
| female_reproductive | 0.07 | 0.00 | 5.13 | 0.14 | 2.52 | 0.40 | 0.04 |
| cornea | 0.07 | 0.00 | 5.30 | 0.17 | 6.88 | 1.47 | 0.04 |
| hepatobiliary | 0.07 | 0.00 | 4.88 | 0.16 | 4.33 | 0.60 | 0.04 |
| tooth | 0.07 | 0.00 | 2.79 | 0.11 | 4.66 | 0.71 | 0.04 |
| lymph_node | 0.07 | 0.00 | 3.39 | 0.13 | 2.64 | 0.47 | 0.04 |
| bladder_wall | 0.07 | 0.00 | 5.26 | 0.17 | 7.34 | 1.40 | 0.04 |
| tongue_papillae | 0.07 | 0.00 | 5.65 | 0.18 | 11.19 | 2.54 | 0.04 |
| compact_bone | 0.07 | 0.00 | 5.76 | 0.17 | 7.50 | 1.44 | 0.04 |
| thick_skin | 0.07 | 0.00 | 6.32 | 0.20 | 6.83 | 1.30 | 0.04 |
| muscular_artery | 0.07 | 0.00 | 5.88 | 0.19 | 6.81 | 1.36 | 0.04 |
| trachea_wall | 0.07 | 0.00 | 5.77 | 0.19 | 5.28 | 1.04 | 0.04 |
| vein_wall | 0.07 | 0.00 | 6.14 | 0.19 | 7.26 | 1.24 | 0.05 |
| lung_acinus_review_v2 | 0.07 | 0.00 | 3.60 | 0.13 | 3.59 | 0.50 | 0.04 |
| skeletal_muscle | 0.07 | 0.00 | 4.82 | 0.16 | 6.80 | 1.27 | 0.04 |
| stomach_wall | 0.07 | 0.00 | 7.32 | 0.23 | 5.37 | 0.93 | 0.05 |
| elastic_artery | 0.07 | 0.00 | 5.17 | 0.18 | 9.86 | 3.05 | 0.04 |
| liver_lobule | 0.07 | 0.00 | 6.32 | 0.16 | 4.40 | 0.64 | 0.04 |
| peripheral_nerve | 0.07 | 0.00 | 4.96 | 0.17 | 5.07 | 1.14 | 0.04 |
| blood_cells | 0.06 | 0.00 | 2.37 | 0.09 | 1.33 | 0.16 | 0.04 |
| oesophagus_wall | 0.07 | 0.00 | 6.62 | 0.21 | 5.77 | 0.91 | 0.05 |
| retina | 0.07 | 0.00 | 5.23 | 0.15 | 2.90 | 0.42 | 0.04 |
| scalp | 0.07 | 0.00 | 5.47 | 0.16 | 3.42 | 0.57 | 0.04 |
| capillary_bed | 0.07 | 0.00 | 3.52 | 0.10 | 1.64 | 0.22 | 0.04 |
| lymph_drainage | 0.07 | 0.00 | 3.46 | 0.12 | 1.29 | 0.22 | 0.04 |
| spleen | 0.06 | 0.00 | 3.57 | 0.12 | 1.24 | 0.23 | 0.04 |

## 4. Settle after a drag, hover pick, labels (wall ms; readbacks)

| model | settle ms (labels off) | readbacks | settle ms (labels on, all items labelled) | readbacks | readback MB | labels found | hover pick ms | readbacks/pick |
|---|---|---|---|---|---|---|---|---|
| pancreas | 24.8 | 0 | 35.2 | 1 | 4.10 | 11 | 0.24 | 2 |
| duodenum | 32.6 | 0 | 79.0 | 1 | 4.10 | 32 | 0.25 | 2 |
| colon_wall | 34.6 | 0 | 47.3 | 1 | 4.10 | 9 | 0.28 | 2 |
| kidney_nephron | 7.9 | 0 | 18.9 | 1 | 4.10 | 14 | 0.25 | 2 |
| jejunum | 15.8 | 0 | 37.9 | 1 | 4.10 | 17 | 0.27 | 2 |
| neuron | 10.3 | 0 | 21.2 | 1 | 4.10 | 14 | 0.22 | 2 |
| ileum | 19.6 | 0 | 49.9 | 1 | 4.10 | 22 | 0.30 | 2 |
| thin_skin | 14.8 | 0 | 47.6 | 1 | 4.10 | 29 | 0.27 | 2 |
| axillary_skin | 24.5 | 0 | 47.2 | 1 | 4.10 | 13 | 0.21 | 2 |
| whole_heart | 12.0 | 0 | 33.8 | 1 | 4.10 | 29 | 0.23 | 2 |
| ear | 10.1 | 0 | 23.0 | 1 | 4.10 | 17 | 0.28 | 2 |
| male_reproductive | 12.1 | 0 | 23.7 | 1 | 4.10 | 12 | 0.23 | 2 |
| cardiac_muscle | 11.1 | 0 | 21.0 | 1 | 4.10 | 8 | 0.27 | 2 |
| thyroid_parathyroid_review_v2 | 8.1 | 0 | 18.3 | 1 | 4.10 | 6 | 0.24 | 2 |
| ileocecal_rectum | 12.1 | 0 | 25.4 | 1 | 4.10 | 12 | 0.25 | 2 |
| eyeball | 10.6 | 0 | 24.8 | 1 | 4.10 | 8 | 0.24 | 2 |
| female_reproductive | 11.1 | 0 | 29.3 | 1 | 4.10 | 14 | 0.29 | 2 |
| cornea | 16.5 | 0 | 43.5 | 1 | 4.10 | 19 | 0.27 | 2 |
| hepatobiliary | 13.7 | 0 | 39.9 | 1 | 4.10 | 35 | 0.25 | 2 |
| tooth | 11.6 | 0 | 29.8 | 1 | 4.10 | 17 | 0.24 | 2 |
| lymph_node | 10.7 | 0 | 44.6 | 1 | 4.10 | 21 | 0.24 | 2 |
| bladder_wall | 17.5 | 0 | 41.6 | 1 | 4.10 | 13 | 0.25 | 2 |
| tongue_papillae | 28.1 | 0 | 62.4 | 1 | 4.10 | 22 | 0.33 | 2 |
| compact_bone | 17.5 | 0 | 64.5 | 1 | 4.10 | 30 | 0.22 | 2 |
| thick_skin | 18.5 | 0 | 48.8 | 1 | 4.10 | 19 | 0.28 | 2 |
| muscular_artery | 17.0 | 0 | 47.2 | 1 | 4.10 | 11 | 0.26 | 2 |
| trachea_wall | 14.9 | 0 | 48.3 | 1 | 4.10 | 17 | 0.25 | 2 |
| vein_wall | 18.7 | 0 | 48.4 | 1 | 4.10 | 11 | 0.21 | 2 |
| lung_acinus_review_v2 | 10.0 | 0 | 23.6 | 1 | 4.10 | 9 | 0.25 | 2 |
| skeletal_muscle | 17.7 | 0 | 44.5 | 1 | 4.10 | 23 | 0.31 | 2 |
| stomach_wall | 16.6 | 0 | 51.0 | 1 | 4.10 | 21 | 0.25 | 2 |
| elastic_artery | 21.0 | 0 | 52.8 | 1 | 4.10 | 13 | 0.24 | 2 |
| liver_lobule | 11.8 | 0 | 69.9 | 1 | 4.10 | 19 | 0.24 | 2 |
| peripheral_nerve | 12.3 | 0 | 35.8 | 1 | 4.10 | 13 | 0.25 | 2 |
| blood_cells | 6.1 | 0 | 22.7 | 1 | 4.10 | 27 | 0.18 | 2 |
| oesophagus_wall | 15.7 | 0 | 61.1 | 1 | 4.10 | 27 | 0.32 | 2 |
| retina | 11.6 | 0 | 50.6 | 1 | 4.10 | 26 | 0.27 | 2 |
| scalp | 12.7 | 0 | 36.2 | 1 | 4.10 | 17 | 0.32 | 2 |
| capillary_bed | 7.0 | 0 | 44.7 | 1 | 4.10 | 35 | 0.26 | 2 |
| lymph_drainage | 6.2 | 0 | 18.5 | 1 | 4.10 | 12 | 0.24 | 2 |
| spleen | 7.8 | 0 | 26.5 | 1 | 4.10 | 14 | 0.25 | 2 |

## 5. Lights and shadows

| model | camera yaw change (deg) | key light world dir A | dir B | light turned (deg) | lights follow camera | shadows enabled in app |
|---|---|---|---|---|---|---|
| pancreas | 179.97 | [0.4036, 0.7261, 0.5567] | [-0.4036, 0.7261, -0.5567] | 86.88 | True | False |
| duodenum | 179.97 | [0.2315, 0.7796, 0.5819] | [-0.2315, 0.7796, -0.5819] | 77.55 | True | False |
| colon_wall | 179.97 | [0.2315, 0.7796, 0.5819] | [-0.2315, 0.7796, -0.5819] | 77.55 | True | False |

Shadow maps are disabled by the viewport (`app/viewer/viewport.py:106` sets `rsettings.shadows = False`), so the shadow pass never runs in the app; `tools/slim/bench_viewer.py` used the renderer default (shadows on).

## 6. Atlas (app/viewport.py + app/renderer.py, Z-Anatomy data)

Structures 4024, triangles 12,635,097, vertices 6,445,277, 28.0 B/vertex, VBO 172.1 MiB, IBO 144.6 MiB, render [2560, 1600], none (the atlas renderer has no multisampled target; it uses FXAA).
Load: dataset 0.041 s, geometry decode 0.248 s, upload 0.135 s, peak RSS 1010.6 MB.

| scenario | settled ms | orbit median ms | orbit p95 | GPU ms | draw calls | model draws | geometry passes | readbacks/frame | readback ms/frame | readbacks first frame after drag | hover pick ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| default settings | 5.0 | 4.9 | 5.3 | 4.3 | 7 | 2 | 2 | 0 | 0.00 | 0 | 0.26 |
| structure labels on | 17.2 | 17.5 | 19.8 | 16.1 | 7 | 2 | 2 | 180 | 13.83 | 180 | 0.28 |

Atlas GPU ms per pass (orbit median):

| scenario | ao_fbo | blur_fbo | gbuffer | hdr_fbo | ldr_fbo | start | target |
|---|---|---|---|---|---|---|---|
| default | 0.07 | 0.13 | 2.85 | 1.14 | 0.03 | 0.00 | 0.05 |
| labels on | 0.07 | 0.13 | 13.73 | 1.14 | 0.03 | 0.00 | 0.93 |

## 7. Stress ramp (model viewer, copies of one model on a grid)

| target | triangles | copies | parts | build scene s | upload s | load total s | B/vertex | VBO MiB | IBO MiB | GPU MiB used (delta) | orbit median ms | GPU ms | draw calls | peak RSS MB | result |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 25M | 29,243,108 | 4 | 1088 | 0.3 | 0.5 | 3.8 | 24.0 | 348 | 350 | 1,671 | 34.7 | 32.7 | 36 | 2,692 | ok |
| 50M | 51,175,439 | 7 | 1904 | 0.6 | 0.9 | 4.5 | 24.0 | 610 | 612 | 2,239 | 45.7 | 44.3 | 82 | 4,487 | ok |
| 100M | 102,350,878 | 14 | 3808 | 1.2 | 1.9 | 6.1 | 24.0 | 1,220 | 1,225 | 3,563 | 50.7 | 59.2 | 138 | 8,865 | ok |
| 150M | 153,526,317 | 21 | 5712 | 1.9 | 3.1 | 8.1 | 24.0 | 1,830 | 1,837 | 4,886 | 51.1 | 88.9 | 154 | 13,058 | ok |
| 250M | 255,877,195 | 35 | 9520 | 3.3 | - | - | - | - | - | - | - | - | - | 15,959 | FAILED |

Failure at 250M: stage 'open': Could not prepare graphics: out of range offset = 0 or size = 1345656; peak RSS 15959.2 MB; GPU used at the time None of 10240 MiB; base model jejunum.

Base model for the copies: jejunum; scene items are capped at 4096 by SceneState.

## 8. Reference set

| model | state | mean RGB | distinct ids in 16x10 pick grid |
|---|---|---|---|
| atlas | default | [30.543, 27.997, 33.129] | 16 |
| atlas | outer_hidden_zoomed_out | [20.713, 24.908, 30.77] | 1 |
| atlas | cut_plane | [23.423, 24.49, 30.125] | 8 |
| atlas | ghosted | [21.679, 24.459, 31.662] | 9 |
| atlas | exploded_mid | n/a for this model |  |
| atlas | animation_mid | n/a for this model |  |
| eyeball | default | [105.239, 90.357, 83.817] | 4 |
| eyeball | outer_hidden_zoomed_out | [37.809, 38.399, 42.432] | 3 |
| eyeball | cut_plane | [61.916, 57.29, 57.759] | 4 |
| eyeball | ghosted | [82.455, 73.338, 70.285] | 3 |
| eyeball | exploded_mid | [100.082, 85.59, 79.206] | 7 |
| eyeball | animation_mid | n/a for this model |  |
| kidney_nephron | default | [53.501, 46.266, 54.417] | 6 |
| kidney_nephron | outer_hidden_zoomed_out | [26.978, 28.828, 36.901] | 7 |
| kidney_nephron | cut_plane | [27.698, 30.244, 36.372] | 1 |
| kidney_nephron | ghosted | [44.723, 42.305, 48.548] | 3 |
| kidney_nephron | exploded_mid | [53.501, 46.266, 54.417] | 6 |
| kidney_nephron | animation_mid | n/a for this model |  |
| pancreas | default | [45.964, 42.942, 48.955] | 8 |
| pancreas | outer_hidden_zoomed_out | [28.758, 31.292, 37.82] | 3 |
| pancreas | cut_plane | [39.268, 37.938, 44.81] | 6 |
| pancreas | ghosted | [41.122, 41.118, 46.106] | 8 |
| pancreas | exploded_mid | [34.522, 36.449, 41.854] | 1 |
| pancreas | animation_mid | n/a for this model |  |
| thin_skin | default | [126.303, 102.425, 93.944] | 19 |
| thin_skin | outer_hidden_zoomed_out | [78.289, 62.492, 67.154] | 13 |
| thin_skin | cut_plane | [83.405, 70.596, 67.688] | 15 |
| thin_skin | ghosted | [112.043, 99.46, 98.116] | 10 |
| thin_skin | exploded_mid | [166.274, 130.496, 121.306] | 19 |
| thin_skin | animation_mid | n/a for this model |  |
| tooth | default | [72.683, 62.112, 59.796] | 9 |
| tooth | outer_hidden_zoomed_out | [52.814, 47.418, 51.116] | 7 |
| tooth | cut_plane | [46.351, 43.42, 45.639] | 8 |
| tooth | ghosted | [72.66, 67.498, 64.143] | 4 |
| tooth | exploded_mid | [72.683, 62.112, 59.796] | 9 |
| tooth | animation_mid | n/a for this model |  |
| whole_heart | default | [103.506, 80.377, 85.541] | 20 |
| whole_heart | outer_hidden_zoomed_out | [74.143, 66.395, 72.088] | 22 |
| whole_heart | cut_plane | [103.506, 80.377, 85.541] | 20 |
| whole_heart | ghosted | [73.064, 61.411, 67.631] | 12 |
| whole_heart | exploded_mid | [103.45, 80.313, 85.231] | 21 |
| whole_heart | animation_mid | n/a for this model |  |

Self-check (two renders of the same states, same machine): 34 images, worst mean abs diff 0.0001, worst % pixels > 8/255 0.0, lowest pick agreement 100.0%.
