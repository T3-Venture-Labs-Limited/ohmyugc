# Spec Delta

## Purpose

Lets users choose any suitable model from any connected provider for each step of making an ad, so the tool keeps working as models change every month.

## ADDED Requirements

### Requirement: Task types
The catalog SHALL classify models into these task types: image generation, image edit (reference-guided composite), image-to-video, talking avatar (image plus audio to video), lip sync (video plus audio to video), speech (text to speech with word timings), background removal, language model, and vision check (image or frame comparison). Each step of the workflow SHALL offer only models of the matching task type.

#### Scenario: Step offers matching models
- **WHEN** a user opens the model picker for storyboard frames
- **THEN** only image-edit models from connected providers are listed

### Requirement: Curated catalog entries
The system SHALL ship curated model entries as data files that declare, per model: provider, model identifier, task type, display name, how workflow inputs map to the model's parameters (first frame, last frame, reference images, reference audio, prompt, duration, resolution, aspect ratio, audio on or off), supported durations, resolutions and aspect ratios, whether it supports multi-shot prompts, and how its price is calculated. Curated entries SHALL be able to declare parameters that the provider's published schema omits.

#### Scenario: Parameter missing from provider schema
- **WHEN** a curated entry declares a `resolution` parameter that the provider's published schema does not list
- **THEN** the system sends that parameter and the model renders at the requested resolution

#### Scenario: User-contributed entry
- **WHEN** a user drops a valid catalog entry file into the user catalog folder
- **THEN** the model appears in the matching picker after the catalog reloads, and an invalid file is reported with the reason instead of crashing the app

### Requirement: Models are chosen by the user, never defaulted
The system SHALL NOT select a model for any task on the user's behalf. Catalog entries SHALL NOT carry default markers. After connecting a key the user SHALL choose the model for each task in Settings (applies to every ad) and MAY choose a different one per ad; a task with no choice SHALL NOT run, and the message SHALL say which choice is missing, or which provider is needed when no connected provider can serve the task.

#### Scenario: Key connected, nothing chosen
- **WHEN** a user connects an OpenRouter key and has not chosen any model
- **THEN** every picker shows "Choose a model…", every step that needs a model refuses to run with a plain sentence saying to choose one, and no provider call or spend happens

#### Scenario: Choice on a disconnected provider
- **WHEN** the chosen model's provider key is removed
- **THEN** the choice no longer counts and the step asks for a new choice

### Requirement: Live model discovery
The system SHALL discover additional models from each connected provider's model listing (OpenRouter image and video model lists, fal model search by category, Replicate collections), cache the results for at most 24 hours, and show discovered models in pickers marked as not curated. A discovered model SHALL be usable when its inputs can be mapped from the provider's metadata or schema; otherwise it SHALL be shown as unavailable with the reason.

#### Scenario: New model appears
- **WHEN** a provider lists a new image-to-video model that accepts a first-frame image
- **THEN** after the next refresh it appears in the clip model picker marked "discovered" with its price if the provider publishes one

#### Scenario: Unmappable model
- **WHEN** a discovered model has no input that can carry the shot's first frame
- **THEN** it is listed as unavailable for image-to-video with the reason "no first-frame input"

#### Scenario: Provider listing unreachable
- **WHEN** a provider's model listing request fails
- **THEN** curated models remain available and the picker notes that discovery for that provider is temporarily unavailable
