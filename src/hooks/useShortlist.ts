import { useCallback, useEffect, useState } from 'react';
import type { ShortlistData } from '../types/housing';

const STORAGE_KEY = 'osu-4bed-shortlist-v1';

function readStorage(): ShortlistData {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ids: [], notes: {} };
    const parsed = JSON.parse(raw) as Partial<ShortlistData>;
    return {
      ids: Array.isArray(parsed.ids) ? parsed.ids.filter((id) => typeof id === 'string') : [],
      notes: parsed.notes && typeof parsed.notes === 'object' ? parsed.notes : {},
    };
  } catch {
    return { ids: [], notes: {} };
  }
}

export function useShortlist() {
  const [data, setData] = useState<ShortlistData>(() => readStorage());

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch {
      // Ignore storage quota errors
    }
  }, [data]);

  const toggleShortlist = useCallback((id: string) => {
    setData((prev) => {
      const exists = prev.ids.includes(id);
      return {
        ...prev,
        ids: exists ? prev.ids.filter((item) => item !== id) : [...prev.ids, id],
      };
    });
  }, []);

  const setNote = useCallback((id: string, note: string) => {
    setData((prev) => ({
      ...prev,
      notes: {
        ...prev.notes,
        [id]: note,
      },
    }));
  }, []);

  const isShortlisted = useCallback(
    (id: string) => data.ids.includes(id),
    [data.ids]
  );

  const getNote = useCallback(
    (id: string) => data.notes[id] ?? '',
    [data.notes]
  );

  return {
    shortlistIds: data.ids,
    notes: data.notes,
    toggleShortlist,
    setNote,
    isShortlisted,
    getNote,
  };
}
