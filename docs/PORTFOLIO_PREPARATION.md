# Portfolio preparation

This copy was exported from the current working tree, including uncommitted development, without the original Git history.

- Removed credentials, seller dumps, runtime artifacts, generated reports and unrelated contract ingestion.
- Replaced the real tenant with a fictional demo tenant.
- Renamed all Russian directory names and updated references in source code, tests and documentation.
- Rewrote the root README around the complete data pipeline.
- Added synthetic test configuration. Corrected a missing April 4 boundary in the financial interval test expectation; collector behavior was unchanged.
- Validation: 146 unit tests passed in the available host environment; Python syntax compilation passed.
- Scanned exported text against long credential values in the source .env and common OpenAI/JWT patterns: no matches. This is a bounded check, not a complete security audit.

The full pipeline was not run against WB, OpenAI or a live database. Fresh-environment dependency installation and Docker integration have not been validated. Original credentials must be revoked separately before any publication of the original repository.
