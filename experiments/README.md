# Isolated Experiments

This directory contains non-production prototypes retained for auditability.
The application under `src/tender_pricing/` does not import them.

- `pipeline_bundle/`: externally supplied parser/matcher bundle, preserved for
  offline compatibility evaluation. Its own copied data directory was not
  supplied, so its standalone test suite is not part of production test discovery.
