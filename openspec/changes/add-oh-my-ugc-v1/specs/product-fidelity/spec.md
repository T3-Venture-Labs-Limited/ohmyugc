# Spec Delta

## Purpose

Keeps the user's real product correct in every ad: generated frames and clips are checked against the real photo, and the shots where accuracy matters most use the real photo itself.

## ADDED Requirements

### Requirement: Drift check on frames
The system SHALL compare every generated frame that shows the product against the product's primary photo and label text using the chosen vision-check model, and SHALL record for each frame: whether the product is present, whether its shape and colours match, whether readable label text matches, and a list of specific issues. The decision to flag a frame SHALL use these yes/no results and the issues list, not a numeric score.

#### Scenario: Misspelled label
- **WHEN** a frame shows the label "COFFE ROASTERS" for a product whose label text is "COFFEE ROASTERS"
- **THEN** the frame is flagged with an issue that names the text mismatch

#### Scenario: Clean frame
- **WHEN** the product, colours and label in a frame match the reference
- **THEN** the frame is marked as passed and shows no warning

#### Scenario: Vision check unavailable
- **WHEN** no vision-check model is available
- **THEN** frames are marked "not checked" and the user can still approve them

### Requirement: Drift check on clips
For every generated clip of a shot that shows the product, the system SHALL sample at least three frames spread across the clip and run the drift check on each, flagging the clip if any sampled frame fails.

#### Scenario: Label garbles in motion
- **WHEN** a clip's middle sampled frame shows a garbled label
- **THEN** the clip is flagged with that frame's timestamp and issues, and offers "New take", "Use real product shot" and "Keep anyway"

### Requirement: Real-product shots
The system SHALL render real-product shots locally from the product cutout (or photo) with no generative model: a choice of motion (slow push-in, pan, parallax, or rotate-in), over a choice of background (a blurred frame from the neighbouring shot, a solid brand colour, or an uploaded image), at the project's resolution and with the shot's duration. The product's pixels SHALL come from the original upload, not from a model.

#### Scenario: Swap a drifted shot
- **WHEN** a user presses "Use real product shot" on a flagged product-in-hand shot
- **THEN** the shot becomes a real-product shot with the same duration and line, renders locally at no cost, and passes the drift check by definition

### Requirement: End card
Every ad SHALL be able to end with an end card that shows the product cutout, the product name, and the brand's call to action and offer as text drawn by the app (not by a model), optionally with the brand logo, for a user-set duration of 1.5 to 5 seconds.

#### Scenario: End card text exact
- **WHEN** an ad is exported with an end card for "LUMA Vitamin C Serum" and call to action "Shop now"
- **THEN** the final frames show exactly those strings in the chosen font, and the product cutout is the uploaded photo
