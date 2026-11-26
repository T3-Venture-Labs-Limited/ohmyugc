# Spec Delta

## Purpose

Turns each approved storyboard shot into a video clip with the model, quality and voice approach the user chose, and lets them review and redo any single shot.

## ADDED Requirements

### Requirement: Voice modes
Each project SHALL use one of three voice modes, choosable per project and overridable per shot:
1. **Native dialogue**: the video model speaks the shot's line itself; when the model accepts reference audio and the actor has a voice sample, that sample SHALL be supplied so the voice stays consistent across shots.
2. **Voiceover**: the line is spoken by a speech model with the actor's voice and laid over a silent clip.
3. **Talking avatar**: the line is spoken by a speech model and the shot's frame plus that audio are sent to a talking-avatar or lip-sync model.

Shots with no spoken line SHALL be generated silent in every mode.

#### Scenario: Native dialogue with voice reference
- **WHEN** a talking shot is rendered in native-dialogue mode on a model that accepts reference audio, and the actor has a voice sample
- **THEN** the request includes the shot's line in the prompt and the actor's voice sample as reference audio

#### Scenario: Native dialogue without voice reference
- **WHEN** native-dialogue mode is chosen on a model with no reference-audio input
- **THEN** the user is warned before rendering that the voice may differ between shots

#### Scenario: Voiceover mode
- **WHEN** a project in voiceover mode is rendered
- **THEN** each line is spoken with the actor's voice using a speech model that returns word timings, and video clips are requested without audio

### Requirement: Draft and final quality
Users SHALL be able to render a draft (low resolution, cheapest settings the model allows, no audio unless the voice mode needs native audio) and a final (720p or 1080p as chosen). Final renders SHALL reuse the same approved frames and prompts as the draft. Users SHALL be able to render final for a subset of shots.

#### Scenario: Draft then final
- **WHEN** a user renders a draft of all shots, then renders final for the approved draft
- **THEN** the final clips use the same first frames and prompts at the higher resolution, and draft clips remain available for comparison

### Requirement: Background rendering and progress
Clip generation SHALL run as background jobs that survive closing the browser and restarting the app, with per-shot status (queued, waiting for rate limit, running, checking, done, failed) and elapsed time visible in the web app and CLI. Shots SHALL be generated in parallel up to a per-provider concurrency limit the user can set.

#### Scenario: Close and return
- **WHEN** a user starts rendering six shots, closes the browser, and reopens the project later
- **THEN** finished shots show their clips and running shots show live status

#### Scenario: One shot fails
- **WHEN** one of six shots fails at the provider
- **THEN** the other shots finish normally, and the failed shot shows the plain-English reason with a "Retry" action

### Requirement: Clip review
Users SHALL be able to play each clip, see its drift-check result, compare takes, keep one take per shot, request a new take (optionally with a changed prompt), switch a shot to a real-product shot, or trim the clip's start and end. Earlier takes SHALL be kept until the project is deleted or the user clears them.

#### Scenario: Pick between takes
- **WHEN** a shot has two takes
- **THEN** the user can play both and mark one as the chosen take, which is the one used in assembly
