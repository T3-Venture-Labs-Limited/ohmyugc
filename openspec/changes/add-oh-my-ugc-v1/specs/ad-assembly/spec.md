# Spec Delta

## Purpose

Stitches the chosen clips into finished, platform-ready ads with voice, music, captions, text cards and an end card, and exports one ad or several hook variants.

## ADDED Requirements

### Requirement: Stitching
The system SHALL assemble the chosen take of every shot, in storyboard order, into one video at the project's aspect ratio (9:16, 1:1, 4:5 or 16:9) and output resolution, normalising frame rate, size and audio format, with hard cuts by default and an optional short crossfade per cut. Clips SHALL be trimmed or held on their last frame to match each shot's spoken-line length where the voice mode provides timings.

#### Scenario: Mixed sources
- **WHEN** an ad contains a 480p talking clip, a 720p cutaway and a locally rendered real-product shot
- **THEN** the exported video is a single file at the chosen resolution with every shot scaled to fill the frame without distortion

### Requirement: Audio mix
The ad's audio SHALL combine native dialogue or voiceover, and an optional music track (uploaded by the user) that is automatically lowered while someone is speaking. Loudness SHALL be normalised to a level suitable for social platforms.

#### Scenario: Music ducking
- **WHEN** an ad with voiceover and a music track is exported
- **THEN** the music is noticeably quieter during speech and returns to its set level in gaps

### Requirement: Captions
Ads SHALL have optional animated word-by-word captions using the caption styles from popcaps. Caption timing SHALL come from the speech model's word timings for voiceover and talking-avatar shots, offset by each shot's start time, and from transcription of the individual clip for native-dialogue shots. Caption words SHALL match the script's spelling, including brand and product names.

#### Scenario: Brand name spelled right
- **WHEN** an ad saying "LUMA" is exported with captions
- **THEN** the caption shows "LUMA", not a transcription guess such as "Luma" or "Looma"

#### Scenario: Timing across shots
- **WHEN** a voiceover line starts 6.8 seconds into the ad after a silent shot
- **THEN** its caption words appear within 0.1 seconds of their spoken times

### Requirement: Text cards and on-screen text
Each shot's on-screen text SHALL be drawn over the shot for its duration in the project's text style, and users SHALL be able to insert full-screen text cards between shots.

#### Scenario: On-screen text
- **WHEN** a shot has the on-screen text "30-day glow challenge"
- **THEN** that text is visible over the shot and not over neighbouring shots

### Requirement: Export and variants
Users SHALL be able to export an MP4 (H.264, AAC) of the ad and, for projects with hook variants, export every variant as a separate file sharing the same body. Only shots that differ between variants SHALL be generated per variant. Exports SHALL include a sidecar SRT caption file on request.

#### Scenario: Three hook variants
- **WHEN** a project with three kept hooks is exported
- **THEN** three MP4 files are produced whose bodies are identical, and only the three hook shots were paid for separately
