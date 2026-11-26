# Spec Delta

## Purpose

Produces the words of the ad, either written by the user or by their own language model from the brand and product context, plus alternative opening hooks to test.

## ADDED Requirements

### Requirement: Pasted script
Users SHALL be able to paste or type a script for a project. The pasted text SHALL be used as written; the system SHALL NOT rewrite it unless the user asks.

#### Scenario: Pasted script kept verbatim
- **WHEN** a user pastes a script and drafts a storyboard
- **THEN** every spoken line in the storyboard comes from the pasted script with its wording unchanged

### Requirement: AI-written script
Users SHALL be able to have their chosen language model write a script from the brand context, product facts, the project brief (goal, format, platform, target length) and an optional free-text prompt. The ad formats offered SHALL include at least: talking head with product, problem and solution, unboxing, demo with voiceover, and testimonial. Generated scripts SHALL fit the target length at a normal speaking pace (about 2.5 words per second) and SHALL be editable before use.

#### Scenario: Write a 30-second script
- **WHEN** a user asks for a 30-second problem-and-solution script for a product
- **THEN** the estimated cost is shown, a script of roughly 65–85 spoken words is returned, and it mentions every must-mention point from the brand

#### Scenario: Claims to avoid detected
- **WHEN** a generated script contains a phrase listed under the brand's claims to avoid
- **THEN** the phrase is highlighted and the user is warned before continuing

#### Scenario: No language model connected
- **WHEN** no connected provider offers a language model
- **THEN** the AI-writing action is disabled with a note naming which providers enable it, and pasting a script still works

### Requirement: Hook variants
Users SHALL be able to generate or write additional opening hooks (the first line or two of the ad) for the same body. Each hook SHALL be stored as a variant of the project that can be rendered and exported separately.

#### Scenario: Three hooks
- **WHEN** a user asks for 3 hook variants of an approved script
- **THEN** three alternative opening lines are produced, each can be edited, kept or discarded, and kept hooks appear as variants when exporting
