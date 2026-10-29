# GGRap ideas backlog

Ideas we want to come back to. Prototype: https://claude.ai/artifact/9aCdDw7XU8L2ouhyGkxGPd

## Five ideas to discuss

1. **AI coach that listens.** Turns your freestyle into text, then highlights your rhymes, counts "uhh"s and pauses, measures syllables per second, and gives a score.
2. **Daily Word Challenge.** Everyone gets the same word each day and posts 8 bars. The community votes and there is a leaderboard. Brings users back every day.
3. **Cypher Chain.** One rapper writes 4 bars, the next continues from the last rhyme, and the chain grows across users.
4. **Beat Switch.** The beat changes style in the middle of a freestyle (for example Trap → Kochari → Drill every 8 bars). You have to adapt your flow live.
5. **Language Switch mode.** Switch between Armenian and English every 4 bars. Unique to GGRap and made for the diaspora.

## Battle format

**Roles**
- 2 MCs.
- Viewers who vote live.
- Optional: 3 judges with scorecards.

**Rounds**
- 3 rounds. The MCs swap who goes first each round.
- Both MCs get the same rhyme pack (5 words × 5 rhymes) or the same picture, so it is fair.
- 16 bars (or 60 seconds) per MC per round, on the same beat.

**Scoring**
- While an MC raps, viewers tap 🔥 the moment a rhyme lands. Each pack word used earns points.
- Judges score rhymes, flow, punchlines and delivery from 1 to 10.
- Final score: 50% crowd, 50% judges. A tie goes to a 4-bar sudden-death round.

**Rules**
- You can't vote for yourself, and votes count only during that MC's turn.
- Insults are part of battle rap. Hate speech and threats get you removed.
- Rooms have age limits.

**What a real battle needs**
- Live audio or video between the two MCs (a streaming service in the full app).
- A server that counts votes in real time.

**Prototype we can build first:** a live battle room where everyone with the link sees the same pack, timer and scoreboard, and votes update for everyone instantly. The MCs rap in person or on a call.

## Other open items

- **Proper artwork for the picture prompts.** Use Higgsfield or Kling (uses credits) instead of the drawn prototype scenes.
- **Beat library plan.** Pick about 10 launch combinations, write Suno prompts and tags for each, and make the beats on a paid Suno plan.
- **Level and goal after choosing a style.** Level: beginner, intermediate or advanced. Goal: practice, battle, record songs or perform.
- **Record and save takes** inside a session, so there is something to post later.
- **App plan:** website first, then the App Store and Google Play using Capacitor. Main category Music, second category Social Networking.

## Problems to solve before building the real app

| Problem | Solution |
|---|---|
| A new beat for every mix: Suno has no official API for apps | A beat engine in the app using real recorded sounds, plus a library of Suno beats made on a paid plan, plus later a music AI API that allows commercial use |
| Too many combinations to make every beat in advance | The recipe system turns any mix into settings, and the app plays the closest beat from the library |
| Artist names (trademark and personal name rights, Apple's rules, Suno blocks names) | Use musical traits only, never names, voices or songs. Show a "not affiliated" note. Get a legal check |
| "All sampled" can mean uncleared samples | Use sounds we own: recordings of Armenian duduk, zurna, dhol and kanun players, commissioned or AI-made sounds, or packs whose license allows app use |
| AI beats come without exact BPM or start point | Analyze each beat when it is added and store its BPM and start point. Add a "tap the tempo" fix |
| Bluetooth headphone delay ruins the rhythm game | A calibration screen, wired headphones recommended, and a native app later |
| Recording vocals: the beat leaks into the mic and drifts out of sync | Headphones prompt, automatic delay correction, compressed uploads |
| Cost of AI beats and audio storage | Reuse beats with similar recipes, set free-tier limits, offer a premium plan |
| Apple requires moderation in apps where users post content | Report and block buttons, a content filter, a contact page, rules for uploads |
| Armenian content is limited online | Record our own sound library and have native speakers check every lyric and tip |
