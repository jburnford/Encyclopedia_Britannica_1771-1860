export const meta = {
  name: 'absorbed-split',
  description: 'Locate absorbed-article boundaries inside oversized records via agent fan-out',
  phases: [{ title: 'Split', detail: 'one agent per batch of absorber records' }],
}

// args = { files: [...batch file paths...], model }
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const files = A.files || []
const model = A.model || 'sonnet'
if (!files.length) return { error: 'no files', argsSeen: args }

const SCHEMA = {
  type: 'object', additionalProperties: false, required: ['results'],
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object', additionalProperties: false, required: ['i', 'splits'],
        properties: {
          i: { type: 'integer' },
          splits: {
            type: 'array',
            items: {
              type: 'object', additionalProperties: false,
              required: ['norm', 'found', 'start_text'],
              properties: {
                norm: { type: 'string' },
                found: { type: 'boolean' },
                start_text: { type: 'string' },
              },
            },
          },
        },
      },
    },
  },
}

const INSTRUCTIONS = `You recover "absorbed" articles in the Encyclopaedia Britannica. When the OCR failed
to mark a headword, that article's text was welded onto the END of the PREVIOUS article's record. Your
job: find where each absorbed article BEGINS inside the oversized body.

Each batch item is one oversized record (the "absorber") with:
  absorber_headword = the record's real headword (its own article is at the START of the body)
  body              = the full body text (absorber's own article + the absorbed article(s) after it)
  absorbed          = headwords that other editions have but this edition is missing; each likely
                      begins somewhere later in the body. Each has: norm, headword, ref (opening of
                      that article in another edition, to help you recognise it).

For EACH absorbed headword, find where its article starts in the body and return:
  found      = true if the article genuinely begins inside this body (a new entry, usually the
               headword in caps possibly OCR-garbled, followed by a definition matching 'ref');
               false if the word only appears in passing prose, or is not in the body.
  start_text = if found, copy VERBATIM the first ~8 words of the absorbed article exactly as they
               appear in the body (must be an exact substring so it can be located). Include the
               headword token itself. If not found, "".

Rules:
  - The absorber's OWN article comes first; do not mark its text as an absorbed start.
  - Absorbed articles appear in alphabetical order after the absorber.
  - The headword in the body may be OCR-garbled or lower-cased; match by content against 'ref'.
  - Return a result object for EVERY item: copy the item's integer "i" field verbatim,
    plus a split entry for EVERY absorbed headword. Do NOT return file/ln — only "i".

Read the batch JSON file at this path and process every item:
`

log(`splitting ${files.length} batch files on ${model}`)
const results = await parallel(files.map((path, bi) => () =>
  agent(INSTRUCTIONS + path, { label: `split:${bi}`, phase: 'Split', model, schema: SCHEMA })
    .then(r => (r && r.results) || [])
))
const all = results.filter(Boolean).flat()
return { results: all, n_out: all.length }
