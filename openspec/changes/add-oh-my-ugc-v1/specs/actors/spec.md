# Spec Delta

## Purpose

Gives each ad a consistent on-screen person, created from a description or an uploaded photo, that stays recognisably the same across every shot and every project.

## ADDED Requirements

### Requirement: Create actor from description
Users SHALL be able to create an actor by describing them (for example age range, look, style, setting) and generating candidate portraits with an image model, then picking one as the actor's reference image.

#### Scenario: Generate candidates
- **WHEN** a user describes "woman in her late 20s, natural makeup, casual knit sweater, phone selfie in a bright kitchen" and asks for 4 candidates
- **THEN** the estimated cost is shown first, four portraits are generated, and the chosen one becomes the actor's reference image

### Requirement: Create actor from photo
Users SHALL be able to create an actor by uploading a photo of a person. The system SHALL NOT require a consent confirmation, and SHALL show a one-line reminder that the user is responsible for having the right to use the likeness.

#### Scenario: Upload face
- **WHEN** a user uploads a portrait photo
- **THEN** the actor is created with that photo as its reference image without any blocking consent step

### Requirement: Character references
Each actor SHALL have a reference image and MAY have additional reference images (for example a full-body shot or a different angle) generated from the reference or uploaded. All references SHALL be passed to image and video models that accept reference images whenever the actor appears in a shot.

#### Scenario: Extra angle
- **WHEN** a user asks for a side-profile reference of an existing actor
- **THEN** a new image is generated from the reference image and, once accepted, is included in the actor's references for later shots

### Requirement: Actor library and voice
Actors SHALL be kept in a library shared across all brands and projects, with name, description, references and an optional default voice (a provider voice id, or an uploaded voice sample for models that accept reference audio). Users SHALL be able to rename, edit and delete actors; deleting an actor SHALL NOT delete projects that used it.

#### Scenario: Reuse actor
- **WHEN** a user starts a new project for a different brand
- **THEN** the same actor can be selected, with its references and default voice

#### Scenario: Delete used actor
- **WHEN** a user deletes an actor that appears in an existing project
- **THEN** the project keeps its already generated frames and clips, and the shot shows that its actor was removed
