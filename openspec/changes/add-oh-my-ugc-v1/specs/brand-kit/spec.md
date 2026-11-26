# Spec Delta

## Purpose

Captures what the AI needs to know about a brand and its products, and keeps the real product photos as the source of truth for every ad.

## ADDED Requirements

### Requirement: Brands with context fields
Users SHALL be able to create, edit and delete brands with these fields: name, description, voice and tone, target audience, must-mention points, claims to avoid, current offer, call to action, website (text only), and optional logo image. Only the name SHALL be required. These fields SHALL be supplied to every AI writing and storyboarding step for that brand's projects.

#### Scenario: Claims to avoid reach the writer
- **WHEN** a brand lists "cures acne" under claims to avoid and the user asks AI to write a script
- **THEN** the request to the language model includes that restriction, and the generated script is checked for the listed phrases with any match flagged to the user

#### Scenario: Minimal brand
- **WHEN** a user creates a brand with only a name
- **THEN** the brand is saved and can be used for a project

### Requirement: Products with photos and facts
Users SHALL be able to add products to a brand by uploading one to eight photos (JPEG, PNG or WebP, up to 20 MB each) and entering a name, key facts and benefits, and the exact text printed on the label. One photo SHALL be marked as the primary photo. Products SHALL be added only by manual upload; the system SHALL NOT connect to online stores.

#### Scenario: Upload product
- **WHEN** a user uploads three photos of a serum bottle and enters the name and label text
- **THEN** the product is saved with the first photo as primary, and the user can change which photo is primary

#### Scenario: Unsupported file
- **WHEN** a user uploads a HEIC or 30 MB file
- **THEN** the upload is rejected with the accepted formats and size limit

### Requirement: Automatic product cutout
When a product photo is added, the system SHALL produce a transparent-background cutout of the product using the chosen background-removal model, and SHALL let the user replace the cutout with their own transparent PNG. The original photo SHALL never be modified.

#### Scenario: Cutout created
- **WHEN** a product photo is uploaded and a background-removal model is available
- **THEN** a cutout is generated, shown next to the original, and its cost is recorded

#### Scenario: No background-removal model available
- **WHEN** no connected provider offers background removal
- **THEN** the product is saved without a cutout and the user is told that real-product shots will use the uncut photo until a cutout is supplied
