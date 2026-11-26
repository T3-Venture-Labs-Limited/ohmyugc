# Spec Delta

## Purpose

Makes every dollar visible: users see what a step will cost before they spend it, what it actually cost afterwards, and never pay twice for the same output.

## ADDED Requirements

### Requirement: Price lookup
The system SHALL determine a price for each model from, in order: the curated catalog entry, the provider's published pricing (OpenRouter model metadata, fal endpoint pricing, Replicate model page pricing), or "unknown". Prices SHALL account for the variables that change them (duration, resolution, audio on or off, image count, characters, tokens). Looked-up prices SHALL be cached for at most 24 hours.

#### Scenario: Resolution and audio change the price
- **WHEN** a user switches a 5-second clip from 480p silent to 720p with audio on a model whose price depends on both
- **THEN** the shown estimate updates to the price for 720p with audio

#### Scenario: Unknown price
- **WHEN** no price can be determined for a discovered model
- **THEN** the estimate shows "price unknown" for that step and the overall total is labelled as partial

### Requirement: Estimate before spending
Before any action that calls a paid model (generating frames, drafting or final clips, voiceover, background removal, AI writing), the system SHALL show the estimated cost of that action, and the storyboard SHALL show a running estimate for rendering the whole ad at the chosen draft and final quality.

#### Scenario: Render button shows cost
- **WHEN** a user views an approved storyboard with five shots
- **THEN** the "Render draft" and "Render final" actions each show their estimated total before being pressed

#### Scenario: CLI estimate
- **WHEN** a user runs a generating CLI command with `--estimate`
- **THEN** it prints the estimated cost and exits without calling any paid model

### Requirement: Actual-cost ledger
The system SHALL record every paid call in a ledger with timestamp, project, step, provider, model, billed units, the estimated cost and the actual cost when the provider reports it (otherwise the estimate, marked as estimated). Users SHALL be able to view per-project and overall spend.

#### Scenario: Project spend
- **WHEN** a user opens a project after rendering it
- **THEN** the project shows its total spend broken down by step and provider

#### Scenario: Failed job not billed
- **WHEN** a provider job fails before producing output and the provider does not bill failures
- **THEN** the ledger records the failed call with a cost of zero

### Requirement: Budget cap
Users SHALL be able to set an optional budget per project. The system SHALL refuse to start an action whose estimate would push the project's spend over its budget, and SHALL explain how much remains.

#### Scenario: Over budget
- **WHEN** a project has a $5 budget, $4.20 already spent, and the user starts a final render estimated at $3.10
- **THEN** the render does not start and the user sees that it needs $3.10 but only $0.80 remains, with a way to raise the budget

### Requirement: No double payment
The system SHALL cache every paid output by a key derived from the provider, model, all inputs (including the content of input files) and parameters, and SHALL reuse the cached output instead of calling the provider when the same request is made again, unless the user explicitly asks for a new take.

#### Scenario: Re-render unchanged shots
- **WHEN** a user changes the line in shot 3 of five and re-renders the ad
- **THEN** only shot 3 (and anything derived from it) is regenerated; the other shots are reused at no cost

#### Scenario: New take
- **WHEN** a user presses "New take" on a shot
- **THEN** the shot is regenerated with a new seed even though its inputs are unchanged, and the cost is shown first
