# Sprint estimation by AI — proof of concept

> [!WARNING]
> **AI-authored:** This change was autonomously planned and implemented by an AI software factory from a human-authored specification, with possible subsequent human review or modification.

> [!WARNING]
> This experiment is effectively abandoned. The generated material is retained primarily as a research artifact.

An early prototype that works by estimating a fixed-seed synthetic sprint history (8 sprints, 40 completed items) with one recorded AI call per condition — unguided, guided by the learned artifact, and full history — and scores the 12-item held-out backlog into a go/no-go verdict. Record shapes and rules: [contract.md](contract.md).

```sh
python3 check.py
python3 check_calibration.py
python3 estimate.py --item recorded/item.json --run-dir recorded --replay
```

## Notes

- spawned from experimenting with no-code Atlassian/Trello sprint estimation flows
- goal; see how the Factory would implement an AI-driven estimation system
- basic model; bootstrap from multiple data sources
- continuous improvement loop; estimate work, compare outcomes, refine future estimates
- intended direction; improve estimation efficiency/accuracy over time
- Factory implementation was not effective
- Atlassian roadmap-based solution worked substantially better
- current implementation not worth pursuing as-is
