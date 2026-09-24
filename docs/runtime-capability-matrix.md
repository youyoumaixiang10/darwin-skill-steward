# Runtime capability matrix

Darwin Core governs evidence, evaluation, approval, promotion, and rollback. Runtime adapters expose only operations supported by documented or user-selected surfaces. A generated package or plan is not proof that the target runtime installed it.

| Runtime | Discovery | Candidate package | Observation | Apply | Rollback | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Codex | User, repository, and plugin Skills | Existing isolated candidate workflow | Hook turn translation; Skill attribution remains `UNKNOWN` without named evidence | Existing exact-approval workflow | Existing exact-approval workflow | Implemented and locally tested |
| Claude Code | User and project `.claude/skills` | Claude plugin ZIP | Hook turn translation; no inferred Skill invocation | Reviewed plugin test/install plan | Reinstall prior reviewed package | Adapter and fixture tests implemented; real-runtime install still requires user verification |
| Claude Cowork | Explicit exported roots | Claude custom plugin ZIP | Unavailable | Manual upload through Customize > Plugins | Reimport prior reviewed plugin | Adapter and fixture tests implemented; manual client verification required |
| WorkBuddy | User and project `.workbuddy/skills` | Documented Skill ZIP with required metadata validation | Unavailable | Manual Add Skill > Upload Skill plan | Reimport prior reviewed ZIP | Adapter and fixture tests implemented; manual client verification required |
| Doubao client | Explicit user-selected export roots | Standard Skill ZIP | Unavailable | Manual Upload Skill plan | Reimport prior reviewed ZIP | Experimental manual adapter; no public automatic-install or telemetry interface verified |

`scripts/runtime.py` exposes `list`, `package`, `plan-apply`, and `plan-rollback` for these adapters. Missing runtime signals remain `UNKNOWN`; Darwin never converts a generated file or an instruction plan into a claimed installation, invocation, or successful outcome.

Primary references used for the implemented package boundaries:

- Claude plugins and Cowork surfaces: <https://support.claude.com/en/articles/13837440-use-plugins-in-claude>
- Anthropic's official Claude plugin structure: <https://github.com/anthropics/claude-plugins-official>
- WorkBuddy Skill package structure: <https://open.workbuddy.cn/docs/skill>
- WorkBuddy local Skill import: <https://www.workbuddy.cn/docs/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market>
