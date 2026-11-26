# Spec Delta

## Purpose

Lets scripts and AI agents drive the whole workflow from a terminal, with machine-readable output, so oh-my-ugc can be automated without the web app.

## ADDED Requirements

### Requirement: Command coverage
The CLI SHALL be installed as `oh-my-ugc` with the alias `omu`, and SHALL cover: starting the web app, settings and keys, model listing and refresh, brands, products, actors, projects (create, show, delete), script writing and hooks, storyboard drafting, frame generation and approval, clip rendering (draft and final), assembly and export, spend reporting, and a diagnostic `doctor` command.

#### Scenario: End to end from CLI
- **WHEN** an agent runs brand, product, actor, project, storyboard, render and export commands in sequence
- **THEN** it produces the same ad the web app would for the same inputs

### Requirement: JSON output
Every CLI command SHALL accept `--json` and then print exactly one JSON document to standard output (progress goes to standard error), and SHALL exit with status 0 on success and non-zero on failure, with failures reported as `{"error": "<plain sentence>"}`.

#### Scenario: Parsable output
- **WHEN** an agent runs `omu projects --json`
- **THEN** standard output parses as JSON listing the projects, and nothing else is printed to standard output

#### Scenario: Error output
- **WHEN** a command fails because no provider key is set
- **THEN** it exits non-zero and prints a JSON object whose `error` field says which key to set

### Requirement: Long jobs from the CLI
Commands that start long jobs SHALL return immediately with the job id unless `--wait` is given, in which case they SHALL block until the job finishes and print its result. A job status command SHALL report progress for a given job id.

#### Scenario: Wait for render
- **WHEN** an agent runs a render command with `--wait --json`
- **THEN** the command exits when all shots finish, printing each shot's status and clip path

### Requirement: Doctor
`omu doctor` SHALL check ffmpeg (including caption support), writable data folders, each provider key's validity, and model catalog health, and print an install hint for each failure appropriate to the user's operating system.

#### Scenario: Missing caption support on macOS
- **WHEN** the only ffmpeg found lacks caption rendering support on macOS
- **THEN** doctor reports it and suggests installing Homebrew `ffmpeg-full`

### Requirement: Agent skill
The repository SHALL include an agent skill file that teaches an AI agent how to make an ad with the CLI, including cost estimates and the approval steps.

#### Scenario: Skill present
- **WHEN** a user installs the skill into an agent
- **THEN** the skill documents every command the agent needs, with `--json` examples
