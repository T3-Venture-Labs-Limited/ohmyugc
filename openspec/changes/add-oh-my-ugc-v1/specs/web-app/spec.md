# Spec Delta

## Purpose

Gives non-technical marketers a local web interface for the whole workflow, from brand kit to exported ad, with costs and approvals visible at every step.

## ADDED Requirements

### Requirement: Local web app
Running `omu` (or `omu serve`) SHALL start a web app on the user's machine, bound to localhost by default, and open it in the browser. The app SHALL work without an internet connection except for provider calls.

#### Scenario: Start
- **WHEN** a user runs `omu`
- **THEN** the app is served on localhost and the browser opens to the projects page

### Requirement: Guided project flow
A project SHALL move through these stages, each reachable from a persistent stage navigator: Brief (brand, product, actor, format, length, platform, voice mode, models), Script, Storyboard, Clips, and Export. A stage SHALL show what is missing before the next stage can start, and SHALL never discard work from later stages without confirmation.

#### Scenario: Missing input
- **WHEN** a user opens the Storyboard stage without a script
- **THEN** the stage explains that a script is needed and links to the Script stage

#### Scenario: Going back
- **WHEN** a user edits the script after frames were generated
- **THEN** the app asks whether to redraft the storyboard or keep it, and keeps it unless the user confirms

### Requirement: Library pages
The app SHALL have pages for projects, brands and products, actors, spend, and settings (provider keys, default models, concurrency, budget defaults).

#### Scenario: First run
- **WHEN** a user opens the app with no provider keys set
- **THEN** settings is shown first with a short explanation of which provider each step needs and where to get a key

### Requirement: Costs and approvals visible
Every control that spends money SHALL display its estimate on or beside the control, and the project header SHALL show the project's spend and budget.

#### Scenario: Cost on button
- **WHEN** a user hovers or focuses "Generate frames"
- **THEN** the estimated cost is already visible without opening another view

### Requirement: Design and accessibility
The app SHALL have its own visual identity distinct from clipyyy, short-stock and popcaps, SHALL use a floating bottom console for the current stage's primary actions, and SHALL be fully usable at 390 px wide and on desktop. It SHALL be operable by keyboard with visible focus, have text contrast of at least 4.5:1, and avoid italic accent words, eyebrow labels above headings and letter-spaced small-caps labels.

#### Scenario: Mobile width
- **WHEN** the app is used at 390 px wide
- **THEN** every stage can be completed with no horizontal scrolling and no control hidden behind another

#### Scenario: Keyboard only
- **WHEN** a user navigates the storyboard with the keyboard
- **THEN** every shot action can be reached and triggered, with a visible focus indicator
