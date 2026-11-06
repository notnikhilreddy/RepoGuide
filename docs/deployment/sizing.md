# Current artifact and sizing measurements — November 6, 2026

Release `release-8594722296f0308e` uses **1 vCPU / 2 GiB per worker**, separately enabled and normally stopped. Native checks used the exact current Answer `f7d908c142f1` and Index `f12c97b03af0` images.

| Current native observation | Answer | Index |
| --- | ---: | ---: |
| Explicit start to model/database ready | 71.82 s | 61.46 s |
| Model process startup | 24.232 s | 19.454 s |
| Representative uncached answer / full small-repository index | 15.77 s | 15.68 s |
| Embedding model loads per process across failure/recovery/repeat | 1 | 1 |
| One-minute sampled memory maximum | 29.395% (~602 MiB) | 22.705% (~465 MiB) |
| One-minute sampled CPU maximum | 97.315% | 96.812% |

These are representative small-repository jobs, not a latency distribution or unlimited capacity test. CloudWatch one-minute service samples do not establish instantaneous process RSS peaks. The full index used a new owner-scoped revision and the repeat was explicitly deduplicated. Same-worker process IDs and the one-time model loads are recorded in `.artifacts/native-2g-metrics.json` and `.artifacts/aws-final-smoke.json`.

The current API ZIP is **5,529,909 bytes** and controller **15,477 bytes**. The exact extracted API with isolated TLS PostgreSQL had warm read p95 **56.7 ms**. Native warm browsing observations were about **62–166 ms**; the evaluation S3 read took **427 ms**. Those native endpoint observations are not p95 measurements. They do not require either worker to run.

Current compressed ECR images are **545,319,749 bytes Answer** and **480,230,608 bytes Index**. Local uncompressed sizes are 2,073,248,733 and 1,947,800,936 bytes. Both remain CPU-only, with pinned bundled weights, no runtime model downloads and role-specific dependencies. The retained current, measured and original recovery pairs total six images. Their logical compressed byte sum is 3,076,624,087 before shared-layer deduplication; this is not billed ECR storage.

The paired quality evaluation used Linux/amd64 containers under Apple Silicon emulation. Its warm p95 changed from 9.8 to 42.4 seconds; it does not measure native Fargate latency. Native evidence supports keeping one vCPU and the smaller 2-GiB allocation for the bounded demo. No allocation was reduced further.

## Historical initial-release measurements

The following November 5 observations apply to the earlier release and are retained for comparison. Their image/package identities and native timings do not describe the current release.

The selected AWS allocation is **1 vCPU / 2 GiB per worker**, independently enabled with default desired count zero. CPU stays at one core because local repeated inference was faster than the half-core allocation; native memory measurements supported removing the extra 2 GiB. Large repositories can require more memory; do not assume the small fixture establishes an unlimited indexing capacity.

| Measurement | Allocation | Observed result |
| --- | --- | --- |
| Local Answer repeated inference | 0.5 vCPU / 2 GiB | 32.02 s ready; warm combined embedding/reranker p50 112 ms, p95 161 ms; peak RSS 727 MiB |
| Local Answer repeated inference | 1 vCPU / 2 GiB | 20.59 s ready; warm combined inference p50 62 ms, p95 66 ms; peak RSS 730 MiB |
| Local pinned RepoGuide full index | 1 vCPU / 4 GiB | 281.24 s; peak process RSS 968.6 MiB |
| Native AWS Answer baseline | 1 vCPU / 4 GiB | Start-to-ready 71.72 s; process startup 22.92 s; answer job 9.3 s; memory maximum 11.694% (~479 MiB) |
| Native AWS Index baseline | 1 vCPU / 4 GiB | Start-to-ready 71.75 s; process startup 22.548 s; MarkupSafe indexing 12.43 s; memory maximum 9.668% (~396 MiB) |
| Native AWS final Answer | 1 vCPU / 2 GiB | Start-to-ready 71.95 s; process startup 22.783 s; live answer 15.52 s; same-process recovery passed |
| Native AWS final Index | 1 vCPU / 2 GiB | Start-to-ready 61.67 s; process startup 19.981 s; full MarkupSafe index 15.54 s; repeated dedup passed |
| Final exact packaged API, local | 512 MiB | Health ~2 ms; first ready 0.99 s; warm list p95 21 ms, isolated TLS PostgreSQL |
| Final AWS API first repository read | 512 MiB | 3.727 s including idle Neon resume/reconnect; subsequent browsing endpoints ~91–315 ms |

Local timings are Linux/amd64 under Apple Silicon emulation, and host contention varies. Fargate start-to-ready includes provisioning/pull/process readiness. CloudWatch service memory percentages are sampled measurements rather than process peak RSS. The 4-GiB native baseline used prior manifest-layer identities; venv/model files are unchanged, but final routing/error-boundary modules were hardened after that baseline. The earlier equivalence receipt applies only to the pre-hardening images. Final exact-digest 2-GiB acceptance and its telemetry are recorded separately; do not label the earlier identity as the final image.

Final 2-GiB CloudWatch samples recorded Answer memory maximum **23.828% (~488 MiB)** and Index **23.608% (~484 MiB)**. CPU maxima were approximately 97–98%, consistent with retaining one full vCPU. These workloads stayed well below the memory allocation; they do not certify arbitrary repository sizes.

Final Lambda REPORT samples recorded **88.6 ms / 118.13 ms init**, separating lightweight Python initialization from managed database resume. After actual Neon resume, first list was **1.8305 s** and warm list **75.6 ms p50 / 207.5 ms p95** over ten measured requests.

## Size and role isolation

The API ZIP is **5,510,470 bytes**, controller **7,504 bytes**. Neither imports ML packages. Final Answer is about **2.073 GB uncompressed / 545.3 MB ECR compressed**; Index **1.948 GB / 480.2 MB**. These are decimal units. CPU PyTorch, transformer dependencies and required inference weights dominate the remaining size.

Role-specific hash-locked requirements and AST-staged application closures omit unnecessary providers/parsers/graph modules by role. Build headers, tests and bytecode are removed. No CUDA/NVIDIA wheels, MLflow server or runtime model downloads are included. The CPU embedding model and Answer reranker revisions are pinned under `deployment/models.json`; base Python/uv images are digest-pinned. Each task gets the included 20 GB ephemeral disk and one owned writable `/tmp` volume.

Tasks are non-root with read-only roots and all Linux capabilities dropped. Both exact local images passed repeated same-process/model-reuse and failed-then-success worker contracts. Scans found no critical, fixable-high or secret findings; unfixed high OS advisories remain documented in `release-evidence.md`.

Use native representative work and memory/OOM telemetry before changing allocations. Keep substantial headroom and preserve the current digest/config for rollback. Do not replace real elapsed idle tests with accelerated clocks or treat a deduplicated index as a second full indexing benchmark.
