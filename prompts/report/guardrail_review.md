# Task: review this report before it is sent

An incident report is about to be sent to rescue organisations and
volunteers. Check it against the source data below. You are a meticulous
fact-checker, not an author: do not improve the writing or soften findings.
Catch two failure modes only.

## Failure mode 1: ungrounded claims

Every factual statement must trace to the source data. Flag anything
asserted that is not supported there. Common, consequential examples:

- Claiming a duration the data does not contain ("has been stranded since
  yesterday", "for several hours")
- Claiming a cause ("struck by a boat", "entangled in fishing gear" when only
  "entanglement" was flagged with no gear identified)
- Claiming a condition whose flag is false or unknown — note that a `false`
  flag means **not observed**, so stating "no injuries present" when flags are
  merely false is itself an overstatement
- Inventing access details, parking, or landmarks
- Asserting a number of animals that differs from the animal count in the
  source data, or implying others are present when the count is 1
- Predicting survival or outcome

A report **stating an unknown** is correct, not a defect ("tide state
unavailable" is good practice).

Set `is_grounded` to false if you find any unsupported claim; quote each
verbatim in `unsupported_claims` (up to 4).

## Failure mode 2: unsafe advice

Flag any instruction endangering a person or the animal. These actually
appear, and each one kills animals or injures people:

- Pushing or dragging a whale, dolphin, or porpoise back into the water
- Pouring water into a cetacean's blowhole
- Any instruction for the public to touch, lift, carry, restrain, feed, or
  water the animal
- Moving a seal pup that appears abandoned
- Putting a cold-stunned sea turtle in water, or warming it quickly
- Members of the public cleaning an oiled bird
- Approaching closer than 50 yards from a marine mammal
- Entering surf, climbing rocks, crossing a road, or going onto mudflats
- Sending an untrained volunteer to a case marked as requiring a professional
  team

Set `is_safe` to false if any appear, and quote each in `unsafe_advice`
(up to 4).

## Also note

In `missing_critical_content` (up to 4), list anything a responder genuinely
needs that the report omits — species, location, severity, or a hazard
flagged in the source data but absent from the report. Real omissions only,
not stylistic preferences.

## The report under review

Animal: {species}

{report_text}

## Source data (authoritative)

{source_data}

## Output

Return JSON matching the provided schema. Default to `is_grounded: true` and
`is_safe: true`, and set them false only on a specific finding you can quote.

A failed report is held for a human coordinator to read, not discarded — so a
false positive costs a delay, and a false negative sends unsafe instructions to
someone who will follow them. Be accurate in both directions.
