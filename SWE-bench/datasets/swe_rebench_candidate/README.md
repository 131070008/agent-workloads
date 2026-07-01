# SWE-rebench Candidate

SWE-rebench is a candidate future input for the software-engineering workload
family.

Current decision:

- Do not vendor SWE-rebench data in the first workload drop.
- Keep SWE-bench Lite as the classic smoke baseline.
- Revisit SWE-rebench when we need larger scale, newer tasks, or stronger
  contamination controls.

Before adding it:

1. Verify upstream license and citation requirements.
2. Decide whether to keep data external instead of committing it.
3. Add a small manifest-only smoke subset first.
4. Confirm the selected agent runner can execute the tasks without a large
   Docker/repository setup burden on Mac.
