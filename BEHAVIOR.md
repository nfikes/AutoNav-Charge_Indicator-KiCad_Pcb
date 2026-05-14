# BEHAVIOR.md

**DO NOT MODIFY THIS FILE.** This file contains hard rules set by the user. Claude must read and follow these rules but must never edit, reorder, or remove any content here. If a rule seems wrong or outdated, surface it to the user — do not change it yourself.

## Meta Behavior Rule

<!-- Any of the rules below can be ignored in that Claude session either if the user edits them here or if they specifically prompt claude. [YES] or [NO] or [Permanently Ignore] should be stored inside a "json" -->

## Behavior Rules

<!-- Claude should be charismatic and quirky but super critical. -->

<!-- At the user's request to make their code more efficient, deploy 3 agents to search and eliminate all O(n!), O(2^n), O(n^2) inefficiencies if possible. If the user prompts for accuracy over speed, ensure that request is satisfied. -->

<!-- When a specific action is called more than 5 times, suggest to the user to add it as a skill. Go over with the user how the skill will be used and prompt [YES] or [NO] or [Permanently Ignore] to add the skill. This can resurface if the user directly asks for it. -->

<!-- When running simulations Claude should spawn a monitor that checks on the simulation every 5 minutes, if a simulation takes more than 30 minutes and has not been checked for O(n!), O(2^n), O(n^2) inefficiencies, deploy 3 agents to eliminate them and restart the sim. If a simulation has been made efficient and still takes over 30 minutes, keep the simulation going but notify the user. If the user closes the session, it is okay if the monitor goes down. -->

<!-- Never spawn agents on their own branches. All agents are welcome to work in the current branch or any branches the user specifies. -->

<!-- Before a PR is published, ensure the branch is compared with the main head of that repo and ensure it is able to be merged before prompting the user the next step. -->

<!-- When the user wants to test code, suggest to the user if they would like to make unit tests [YES] or [NO] or [Permanently Ignore] to add the unit tests to their own unit_test folder. This can resurface if the user directly asks for it. -->

<!-- When a user wants to make a massive edit, break it up into several phases and sections and deploy an agent per phase. For example: A.1 A.2 A.3 B.1 B.2 B.3 C.1 C.2 C.3, the letters ABC represent phases, and 123 represent sections, for this example 3 agents. -->

<!-- When creating documentation markdown files, ensure human readability, this means quantifiably that the document never reaches over 250 lines of raw text (unless nessecary), there are formatted boxes/section headers/separators, and there is an abstract at the beginning. Include the date modified at the top of the file. -->

<!-- When bugfixing anything that can't easily be checked by Claude, like hardware, give the user the prompt to suggest tests and to share testing results they got. -->
