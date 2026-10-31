# Legacy reference only

This directory preserves the pre-2.0 implementation for reference. It is not
supported, installed, or deployed. Its Flask 1.x dependency list was removed
during the security audit; do not run this code or recreate its admin routes.
Use the root README, pyproject.toml, and hashed locks for the maintained
`lifetime/` application. Historical SQL seeds contain reference data/schema
only; never commit request logs or private configuration.
