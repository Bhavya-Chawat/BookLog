-- =====================================================================
-- 005: mood tags (fills the ER diagram's TAG / BOOK_TAG tables)
--
-- Every book gets moods such as Dark, Cosy or Funny, derived from:
--   * its genres     (e.g. Horror, Gothic       -> Dark)
--   * its description (e.g. "hilarious", "witty" -> Funny)
-- The rules are rows in mood_rule, so they can be read and changed with SQL.
-- tag_book_moods() applies them; a trigger re-tags a book whenever a genre
-- is added to it or its description changes, so new and edited books are
-- tagged automatically.
--
-- Run: psql -d booklog -f backend/db/migrations/005_mood_tags.sql
-- Safe to run again.
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS mood_rule (
    tag_id    INT PRIMARY KEY REFERENCES tag(tag_id) ON DELETE CASCADE,
    genres    TEXT[] NOT NULL DEFAULT '{}',   -- a book in any of these genres gets the mood
    keywords  TEXT,                           -- or: a case-insensitive regex on the description
    blurb     TEXT                            -- shown in the UI
);
-- the API role must read the rules (the trigger runs as the user who inserts the genre)
DO $$
BEGIN
    IF (SELECT relowner::regrole::text FROM pg_class WHERE oid = 'mood_rule'::regclass) <> 'booklog_app' THEN
        ALTER TABLE mood_rule OWNER TO booklog_app;
    END IF;
END $$;

-- The moods (tag_type = 'mood')
INSERT INTO tag (name, tag_type) VALUES
    ('Dark', 'mood'), ('Cosy', 'mood'), ('Funny', 'mood'), ('Romantic', 'mood'),
    ('Tense', 'mood'), ('Mysterious', 'mood'), ('Adventurous', 'mood'), ('Emotional', 'mood'),
    ('Hopeful', 'mood'), ('Thought-provoking', 'mood'), ('Inspiring', 'mood'),
    ('Informative', 'mood'), ('Whimsical', 'mood')
ON CONFLICT (name, tag_type) DO NOTHING;

-- \m and \M are word boundaries, so "dark" matches but "darkroom" does not
INSERT INTO mood_rule (tag_id, genres, keywords, blurb)
SELECT t.tag_id, r.genres, r.keywords, r.blurb
FROM (VALUES
    ('Dark',              ARRAY['Horror','Gothic','Dystopian','True Crime','Psychological Suspense','Paranormal','War'],
                          '\m(dark|bleak|haunting|haunted|sinister|grim|brutal|nightmare|macabre)\M',
                          'Shadows, dread and hard truths'),
    ('Cosy',              ARRAY['Children''s','Fairy Tales','Food'],
                          '\m(cozy|cosy|heartwarming|feel[- ]good|comforting)\M',
                          'A warm drink of a book'),
    ('Funny',             ARRAY['Humor','Satire'],
                          '\m(hilarious|funny|comic|comedy|witty|laugh[- ]out[- ]loud|absurd)\M',
                          'Laugh-out-loud and witty'),
    ('Romantic',          ARRAY['Romance'],
                          '\m(love story|falls? in love|romance|lovers)\M',
                          'Love stories and longing'),
    ('Tense',             ARRAY['Thriller','Crime','Psychological Suspense','Murder Mystery','Detective Fiction'],
                          '\m(thriller|suspense|race against time|chilling|deadly|killer|manhunt)\M',
                          'Page-turners you can''t put down'),
    ('Mysterious',        ARRAY['Mystery','Detective Fiction','Murder Mystery','Investigation','Magical Realism'],
                          '\m(mystery|mysterious|secrets?|riddle|unexplained|disappearance|whodunit)\M',
                          'Secrets, clues and puzzles'),
    ('Adventurous',       ARRAY['Adventure','Fantasy','Space Opera','Quest','Western','YA Fantasy','Travel'],
                          '\m(quest|journey|expedition|voyage|adventure)\M',
                          'Quests, journeys and far-off worlds'),
    ('Emotional',         ARRAY['Literary Fiction','Coming-of-Age','Memoir','Drama','Poetry'],
                          '\m(grief|loss|heartbreaking|moving|tearjerker|heart[- ]wrenching|tender)\M',
                          'Big feelings, bring tissues'),
    ('Hopeful',           ARRAY['Spirituality'],
                          '\m(hope|hopeful|uplifting|redemption|second chance|resilience|healing)\M',
                          'Light at the end of the tunnel'),
    ('Thought-provoking', ARRAY['Philosophy','Essays','Politics','Society','Religion','Dystopian'],
                          '\m(thought[- ]provoking|morality|meaning of life|human nature|provocative)\M',
                          'Ideas that stay with you'),
    ('Inspiring',         ARRAY['Self-Help','Biography','Business','Memoir'],
                          '\m(inspiring|inspirational|triumph|overcome|courage|extraordinary life)\M',
                          'Real people, real lessons'),
    ('Informative',       ARRAY['Science','Popular Science','Technology','History','Economics','Psychology',
                                'Nature','Art','Music','Film','Health'],
                          NULL,
                          'Learn something new'),
    ('Whimsical',         ARRAY['Fairy Tales','Magical Realism','Mythology'],
                          '\m(whimsical|enchanting|enchanted|magical|fairy|talking animals?)\M',
                          'Playful, magical and strange')
) AS r(name, genres, keywords, blurb)
JOIN tag t ON t.name = r.name AND t.tag_type = 'mood'
ON CONFLICT (tag_id) DO UPDATE
    SET genres = EXCLUDED.genres, keywords = EXCLUDED.keywords, blurb = EXCLUDED.blurb;

-- (Re)tag one book, or every book when p_book_id is NULL. Returns the number of tags written.
CREATE OR REPLACE FUNCTION tag_book_moods(p_book_id INT DEFAULT NULL) RETURNS INT
LANGUAGE plpgsql AS $$
DECLARE
    n INT;
BEGIN
    DELETE FROM book_tag bt
    USING tag t
    WHERE t.tag_id = bt.tag_id AND t.tag_type = 'mood'
      AND (p_book_id IS NULL OR bt.book_id = p_book_id);

    INSERT INTO book_tag (tag_id, book_id)
    SELECT DISTINCT r.tag_id, b.book_id
    FROM mood_rule r
    CROSS JOIN book b
    WHERE (p_book_id IS NULL OR b.book_id = p_book_id)
      AND (EXISTS (SELECT 1 FROM book_genre bg JOIN genre g USING (genre_id)
                   WHERE bg.book_id = b.book_id AND g.name = ANY (r.genres))
           OR (r.keywords IS NOT NULL AND b.description ~* r.keywords))
    ON CONFLICT DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$;

CREATE OR REPLACE FUNCTION trg_tag_moods() RETURNS TRIGGER
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM tag_book_moods(NEW.book_id);
    RETURN NULL;
END;
$$;

-- CREATE OR REPLACE (not DROP + CREATE) so a re-run never needs an exclusive lock on book
CREATE OR REPLACE TRIGGER book_genre_moods
    AFTER INSERT ON book_genre
    FOR EACH ROW EXECUTE FUNCTION trg_tag_moods();

CREATE OR REPLACE TRIGGER book_description_moods
    AFTER UPDATE OF description ON book
    FOR EACH ROW WHEN (OLD.description IS DISTINCT FROM NEW.description)
    EXECUTE FUNCTION trg_tag_moods();

CREATE INDEX IF NOT EXISTS idx_book_tag_book ON book_tag (book_id);

-- Tag the whole catalogue now
SELECT tag_book_moods() AS tags_written;

COMMIT;
