# Mineral Identification from Field Observations

Given a field geologist's hand-specimen observations of an unknown mineral — crystal system, Mohs hardness, streak color, body color, luster, and specific gravity — name the single most likely mineral species out of 98 candidates. This task measures how well a model identifies minerals closed-book versus with retrieval over a mineral catalog, and it is the public leaderboard half of a two-layer RRF-hybrid-retrieval evaluation built for the Elastic AgentHack.

## Task

Each case gives observed physical properties (never the chemical formula — that would give the answer away) and asks for the species name only, one lowercase word. The reference document is a 98-species property handbook so retrieval-augmented runs can match observations against catalog entries; closed-book runs must recall the species from the properties alone.

## Scoring

The judge normalizes the answer and reference species name (lowercasing, stripping punctuation, and collapsing known synonyms and transliterations such as creedite/credit, stibnite/antimonite, labradorite/labrador) and requires an exact match. One point per correct species, accuracy over all cases.

## Data and licensing

Reference descriptions are excerpts from English Wikipedia (CC BY-SA 4.0). Physical-property values (Mohs hardness, streak, crystal system) are objective measurements. No Mindat data or specimen images are redistributed here.
