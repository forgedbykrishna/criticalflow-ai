# ABEND References
## S0C4
- **Description**: Storage Protection Exception. Occurs when a program attempts to reference storage that it is not authorized to access, often due to an invalid pointer, uninitialized variable, or out-of-bounds array access.
- **Remediation**: Review recent code changes, check for uninitialized pointers in the failing module, and analyze SYSUDUMP or CEEDUMP output.