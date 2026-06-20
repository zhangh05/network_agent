# Baseline: Legacy Network Links Deleted

## Commit

main HEAD: 275800d

## Completed

- Removed old network fine tools.
- Removed old capability action IDs.
- Removed old registry / namespace / governance entries.
- Removed old skill adapter directory.
- Removed old config translation capability/tool shell.
- Removed old parser handlers.
- Removed old PCAP backend re-export compatibility names.
- Removed old prompt/safe_context network prefix special cases.

## Removed IDs

- network.config.parse
- network.config.translate
- network.config.analyze
- network.interface.extract
- network.route.extract
- network.pcap.parse
- network.pcap.session
- network.pcap.filter
- network.pcap.align
- network.pcap.analyze

## Remaining Entry Points

Tools:

- config.analysis.run
- pcap.analysis.run

Capability actions:

- config.analysis
- config.translation
- pcap.analysis

## Validation

- Hard scan: no legacy IDs / code shells in runtime source.
- Hard scan: no legacy adapter / parser handler / pcap re-export.
- Tests: full pytest passed.
- CI: lint and test passed.

## Notes

This is the clean baseline before any new capability expansion.
