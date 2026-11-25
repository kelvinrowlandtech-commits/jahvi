"""
seed_effects.py
Adds a few starter effects to the effect_presets table:   python seed_effects.py
Each effect = two raw FFmpeg filter strings (no [labels], no ';'):
  global_filter    -> the whole video
  headshot_filter  -> only around each headshot; put enable='{ENABLE}' on EVERY filter in it
Edit / add rows here or directly in the database. Rows with active=false are never picked.
"""
from database import EffectPreset, SessionLocal, init_db

STARTERS = [
    # class_name, name, style (small description), global_filter, headshot_filter
    ("Rage", "Blood Red", "Hot red grade, punchy on the kill",
     "eq=contrast=1.12:saturation=1.3",
     "colorbalance=rs=0.35:gs=-0.1:bs=-0.25:enable='{ENABLE}',eq=contrast=1.3:saturation=1.8:enable='{ENABLE}'"),
    ("Rage", "Red Flash", "Bright saturated flash on the headshot",
     "",
     "eq=saturation=2.6:brightness=0.06:contrast=1.35:enable='{ENABLE}'"),
    ("Cinematic", "Teal Noir", "Cool, darker look with a vignette",
     "eq=contrast=1.1:saturation=0.9,vignette=PI/5",
     "eq=contrast=1.4:saturation=0.6:brightness=-0.03:enable='{ENABLE}'"),
    ("Funk", "Neon Pop", "Colour-shifted pop on every hit",
     "hue=s=1.25",
     "hue=h=35:s=2.2:enable='{ENABLE}'"),
]

if __name__ == "__main__":
    init_db()
    with SessionLocal() as db:
        existing = {(e.class_name, e.name) for e in db.query(EffectPreset).all()}
        added = 0
        for class_name, name, style, global_filter, headshot_filter in STARTERS:
            if (class_name, name) in existing:
                continue
            db.add(EffectPreset(class_name=class_name, name=name, style=style,
                                global_filter=global_filter, headshot_filter=headshot_filter, active=True))
            added += 1
        db.commit()
    print(f"added {added} effect(s)")
