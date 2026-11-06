# Artifact and sizing measurements

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
