# Operations Runbooks
## Resource Exhaustion & CPU Spikes
- **Description**: High system resource utilization (CPU > 90%) or high error rates during heavy transaction volumes, even with normal completion codes (RC 0008).
- **Remediation**: Identify CPU-intensive jobs, review batch scheduling windows, shift workloads, or redistribute resources across LPARs.