# Production lessons

reelhawk is a clean-room generalization of a clipping agent that has been
publishing daily vertical clips from long-form Portuguese-language live
streams since mid-2026, with a human approval step in front of every post.
These are the rules that survived contact with production. Every one of them
was learned by shipping a bad clip or by silently shipping nothing.

## Cutting

**A clip must contain its payoff.** The single biggest source of bad clips is
an ending that cuts the speaker mid-reasoning. Mechanical duration limits love
to do this. reelhawk enforces it twice: boundaries snap to sentence ends at
mine time, and the gate re-checks the final word and (optionally) asks an LLM
whether the payoff the opening promises is actually delivered.

**When a clip is too long, trim the head, never the tail.** The payoff lives
at the end. Advancing the start to the next sentence boundary loses setup you
can survive without; trimming the end loses the reason the clip exists. This
sounds obvious and was still implemented backwards once, which produced a week
of clips that ended one sentence too early.

**Multi-speaker moments get the full frame.** If anyone else is talking, a
tight crop on one face reads as cutting the other person out of their own
conversation. Diarization percentages lie about this (crosstalk, backchannel,
laughter); face counting is more honest. When more than ~30% of sampled frames
show two or more faces, reelhawk refuses the face crop and renders panorama.

## Supply

**Datacenter IPs get bot-walled, and cookies are never the answer.** If you
run the pipeline on a server, video downloads will eventually start failing
with bot checks, and no amount of cookie refreshing fixes it permanently. The
week we spent believing "stale cookies" was the problem was a week of false
alarms. What works: run downloads from a residential connection (a laptop cron
is enough) and feed the server local files. Channel LISTING keeps working from
servers; only media downloads are walled, which is why `reelhawk daily` can
scan a channel from anywhere but you should hand it files where that applies.

**A 403 after years of working downloads usually means your downloader is
stale, not that you are blocked.** Update yt-dlp before buying proxies. (The
same lesson generalizes: try client impersonation before infrastructure.)

## State

**Mine deep once, bank many, publish daily.** A single one-hour video yields
multiple gate-passing clips. The expensive run is the mine; publishing the
next banked clip costs nothing. Design the ledger around segments, not videos,
and never mark a video "done" just because it was visited once — it is done
when its good moments are used up.

**Cache every stage artifact.** Transcription is the slowest stage and never
changes for a given file. Words, candidates, face timelines, renders, and gate
verdicts all live in the workdir; a crashed run resumes instead of restarting.

## Honesty

**Gates fail closed.** A clip with no PASS verdict does not leave the workdir.
If the LLM reviewer is unreachable, that is a FAIL, not a PASS — silence beats
an ungraded publish.

**A dry day reports why.** "No new videos" alarms that hardcode a plausible
story (in our case: "YouTube is blocking us") will eventually hardcode a lie,
and you will debug the wrong thing for days. When `daily` publishes nothing,
it prints the actual reason derived from actual state: nothing banked, no
unmined video of sufficient length, or mined-but-nothing-passed.

**Never pad a dry day.** A day with no good clip is a skipped day, not a day
with a bad clip. The gate exists precisely for the days you are tempted to
override it.

## Rendering

**Extract frames with ffmpeg, not cv2.VideoCapture.** VideoCapture silently
fails on AV1 sources — it returns garbage instead of raising, which turned a
face-position guard into a no-op for weeks. ffmpeg single-shot seeks are
slower and correct.

**Normalize loudness.** Platforms normalize to about -14 LUFS. A clip that is
quieter than its neighbors reads as low quality before a single word lands.

**Prefer h264 sources at download time.** AV1 breaks more downstream tools
than it saves bandwidth.

## Publishing

**Keep a human in front of the post button while you tune the gate.** The
agent's judgment of "good clip" converges on yours only if you keep rejecting
its mistakes. Export mode is the default for a reason.

**Disclose the automation.** A short "clipped and captioned by an AI agent"
line in the caption costs nothing and buys trust. reelhawk has a config field
for it (`post.disclosure`).
