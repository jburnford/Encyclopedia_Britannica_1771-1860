export const meta = {
  name: 'headword-adjudicate',
  description: 'Adjudicate cross-edition OCR headword corrections via agent fan-out',
  phases: [{ title: 'Adjudicate', detail: 'one agent per batch of candidates' }],
}

// args = { files: [...batch file paths...], model: 'haiku'|'sonnet' }
const A = typeof args === 'string' ? JSON.parse(args) : (args || {})
const files = A.files || []
const model = A.model || 'sonnet'
if (!files.length) {
  log('NO FILES — args was: ' + JSON.stringify(args))
  return { error: 'no files in args', argsSeen: args }
}

const DECISION_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['decisions'],
  properties: {
    decisions: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['i', 'decision', 'canonical'],
        properties: {
          i: { type: 'integer' },
          decision: { type: 'string', enum: ['correct', 'keep'] },
          canonical: { type: ['string', 'null'] },
        },
      },
    },
  },
}

const INSTRUCTIONS = `You are correcting OCR errors in Encyclopaedia Britannica article headwords.
The same articles recur across six editions, so a headword spelling found in only ONE edition is
suspect when a near-identical spelling is confirmed in OTHER editions at the same alphabetical slot.

Each candidate has:
  v   = the variant headword (appears in only one edition)
  ed  = that edition
  sug = candidate canonical spellings from OTHER editions; each has n (spelling), d (edit distance
        from v), ne (how many editions contain it). The variant's own edition is NOT among them.
  snip= the opening of the article body (often spells the word out, e.g. "ABACTORES, or ABACTORS, ...")

For EACH candidate decide:
  - "correct": v is an OCR misspelling of one suggestion -> set canonical to that suggestion's n.
  - "keep":    v is a genuinely DISTINCT headword (or you are unsure) -> canonical = null.

Rules:
  - Prefer the suggestion with the lowest d and highest ne.
  - Use the snippet: if it spells the headword the same as v, or as a suggestion, that is strong evidence.
  - BE CONSERVATIVE. The encyclopedia is full of distinct place names, Latin/Greek terms, and
    botanical/zoological genera that differ by 1-2 letters (e.g. CALAMITES vs CALAMINE, CATAPASM vs
    CATAPLASMA are DIFFERENT words). When v could plausibly be its own real entry, choose "keep".
  - A pure OCR garble (letters that are not a real word: CONSTANTINOPE, AMPHISBNA, DESION) -> "correct".
  - Return a decision for EVERY candidate i in the batch.

Use the Read tool to read the candidate batch JSON file at this path, then adjudicate every entry:
`

log(`adjudicating ${files.length} batch files on ${model}`)

const results = await parallel(files.map((path, bi) => () =>
  agent(INSTRUCTIONS + path,
        { label: `adjudicate:${bi}`, phase: 'Adjudicate', model, schema: DECISION_SCHEMA })
    .then(r => (r && r.decisions) || [])
))

const all = results.filter(Boolean).flat()
return { decisions: all, n_out: all.length }
