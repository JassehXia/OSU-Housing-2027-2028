import { useEffect, useState } from 'react';
import type { IsochroneGeoJSON, ListingsDataset } from '../types/housing';

interface HousingDataState {
  dataset: ListingsDataset | null;
  isochrone: IsochroneGeoJSON | null;
  loading: boolean;
  error: string | null;
}

export function useHousingData(): HousingDataState {
  const [state, setState] = useState<HousingDataState>({
    dataset: null,
    isochrone: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [listingsRes, isoRes] = await Promise.all([
          fetch('/data/listings.json'),
          fetch('/data/isochrone.geojson').catch(() => null),
        ]);

        if (!listingsRes.ok) {
          throw new Error(`Failed to load listings (${listingsRes.status})`);
        }

        const dataset = (await listingsRes.json()) as ListingsDataset;

        let isochrone: IsochroneGeoJSON | null = null;
        if (isoRes && isoRes.ok) {
          try {
            isochrone = (await isoRes.json()) as IsochroneGeoJSON;
          } catch {
            isochrone = null;
          }
        }

        if (!cancelled) {
          setState({
            dataset,
            isochrone,
            loading: false,
            error: null,
          });
        }
      } catch (err) {
        if (!cancelled) {
          setState({
            dataset: null,
            isochrone: null,
            loading: false,
            error: err instanceof Error ? err.message : 'Unable to load housing data',
          });
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}
