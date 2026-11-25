import { useEffect, useRef } from 'react';
import L from 'leaflet';
import { Compass, Layers, Maximize2 } from 'lucide-react';
import type { IsochroneGeoJSON, Listing, PriceMode } from '../types/housing';
import {
  formatCurrency,
  getListingPrice,
  getPriceTier,
  OSU_OVAL,
  TIER_COLORS,
} from '../utils/format';

interface HousingMapProps {
  listings: Listing[];
  isochrone: IsochroneGeoJSON | null;
  center: [number, number];
  selectedId: string | null;
  hoveredId: string | null;
  shortlistIds: string[];
  priceMode: PriceMode;
  priceThresholds: { low: number; high: number };
  showBoundary: boolean;
  onToggleBoundary: () => void;
  onSelectListing: (id: string | null) => void;
  onHoverListing: (id: string | null) => void;
  flyToRequest: { lat: number; lng: number; seq: number } | null;
  sidebarOpen: boolean;
  detailOpen: boolean;
}

function createListingIcon(
  color: string,
  borderColor: string,
  isSelected: boolean,
  isHovered: boolean,
  isShortlisted: boolean
): L.DivIcon {
  const active = isSelected || isHovered;
  const size = isSelected ? 22 : isHovered ? 20 : isShortlisted ? 17 : 14;
  const ring = isSelected
    ? 'box-shadow: 0 0 0 4px rgba(186,12,47,0.28), 0 4px 12px rgba(15,23,42,0.35);'
    : isHovered
      ? 'box-shadow: 0 0 0 3px rgba(15,23,42,0.18), 0 3px 8px rgba(15,23,42,0.3);'
      : 'box-shadow: 0 1px 4px rgba(15,23,42,0.32);';

  const starBadge = isShortlisted
    ? `<span style="
        position:absolute;
        top:-5px;
        right:-5px;
        width:12px;
        height:12px;
        border-radius:9999px;
        background:#f59e0b;
        border:1.5px solid #ffffff;
        display:flex;
        align-items:center;
        justify-content:center;
        font-size:8px;
        line-height:1;
        color:#ffffff;
        font-weight:700;
        box-shadow:0 1px 2px rgba(0,0,0,0.25);
      ">★</span>`
    : '';

  const html = `
    <div style="
      position:relative;
      width:${size}px;
      height:${size}px;
      border-radius:9999px;
      background:${color};
      border:${active ? '2.5px' : '2px'} solid ${isSelected ? '#ffffff' : '#ffffff'};
      outline:${isSelected ? `2px solid ${borderColor}` : 'none'};
      ${ring}
      transition: transform 0.14s ease, width 0.14s ease, height 0.14s ease;
      cursor:pointer;
    ">${starBadge}</div>
  `;

  return L.divIcon({
    className: 'housing-dot-marker',
    html,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function createOsuCampusIcon(): L.DivIcon {
  const html = `
    <div style="
      display:flex;
      align-items:center;
      gap:5px;
      background:#BA0C2F;
      color:#ffffff;
      padding:4px 9px 4px 6px;
      border-radius:9999px;
      border:2px solid #ffffff;
      box-shadow:0 4px 14px rgba(186,12,47,0.42), 0 1px 3px rgba(15,23,42,0.2);
      font-weight:700;
      font-size:11px;
      letter-spacing:0.02em;
      white-space:nowrap;
      transform:translate(-50%, -50%);
    ">
      <span style="
        display:inline-flex;
        align-items:center;
        justify-content:center;
        width:18px;
        height:18px;
        border-radius:9999px;
        background:#ffffff;
        color:#BA0C2F;
        font-weight:800;
        font-size:11px;
      ">O</span>
      <span>OSU Oval</span>
    </div>
  `;

  return L.divIcon({
    className: 'osu-campus-marker',
    html,
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  });
}

export function HousingMap({
  listings,
  isochrone,
  center,
  selectedId,
  hoveredId,
  shortlistIds,
  priceMode,
  priceThresholds,
  showBoundary,
  onToggleBoundary,
  onSelectListing,
  onHoverListing,
  flyToRequest,
  sidebarOpen,
  detailOpen,
}: HousingMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const boundaryLayerRef = useRef<L.GeoJSON | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const markerMapRef = useRef<Map<string, L.Marker>>(new Map());
  const osuMarkerRef = useRef<L.Marker | null>(null);

  // Store latest callbacks in refs so Leaflet event listeners never go stale
  const onSelectRef = useRef(onSelectListing);
  const onHoverRef = useRef(onHoverListing);
  onSelectRef.current = onSelectListing;
  onHoverRef.current = onHoverListing;

  // Initialize Leaflet map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      center: OSU_OVAL,
      zoom: 13,
      zoomControl: false,
      preferCanvas: false,
    });

    const cartoApiKey = import.meta.env.VITE_CARTO_API_KEY?.trim();
    const tileUrl = cartoApiKey
      ? `https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png?key=${encodeURIComponent(cartoApiKey)}`
      : 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

    L.tileLayer(tileUrl, {
      attribution: cartoApiKey
        ? '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
        : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      ...(cartoApiKey ? { subdomains: 'abcd' } : {}),
      maxZoom: 19,
    }).addTo(map);

    L.control.zoom({ position: 'bottomright' }).addTo(map);

    markersLayerRef.current = L.layerGroup().addTo(map);

    const campusMarker = L.marker(OSU_OVAL, {
      icon: createOsuCampusIcon(),
      zIndexOffset: 900,
      interactive: true,
    })
      .bindTooltip('The Ohio State University — The Oval', {
        direction: 'top',
        offset: [0, -16],
        className: 'osu-tooltip',
      })
      .addTo(map);

    osuMarkerRef.current = campusMarker;

    map.on('click', () => {
      onSelectRef.current(null);
    });

    mapRef.current = map;

    const resizeObserver = new ResizeObserver(() => {
      map.invalidateSize();
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
      markersLayerRef.current = null;
      boundaryLayerRef.current = null;
      osuMarkerRef.current = null;
      markerMapRef.current.clear();
    };
  }, []);

  // Keep OSU campus marker synced if dataset specifies slightly different center
  useEffect(() => {
    if (osuMarkerRef.current) {
      osuMarkerRef.current.setLatLng(center);
    }
  }, [center]);

  // Invalidate map size when panels toggle
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const timer = window.setTimeout(() => map.invalidateSize(), 220);
    return () => window.clearTimeout(timer);
  }, [sidebarOpen, detailOpen]);

  // Render / toggle 20-minute drive boundary GeoJSON
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (boundaryLayerRef.current) {
      map.removeLayer(boundaryLayerRef.current);
      boundaryLayerRef.current = null;
    }

    if (showBoundary && isochrone && isochrone.features?.length > 0) {
      const layer = L.geoJSON(isochrone, {
        interactive: false,
        style: {
          color: '#BA0C2F',
          weight: 2,
          opacity: 0.55,
          dashArray: '7 6',
          fillColor: '#BA0C2F',
          fillOpacity: 0.045,
        },
      });
      layer.addTo(map);
      layer.bringToBack();
      boundaryLayerRef.current = layer;
    }
  }, [isochrone, showBoundary]);

  // Render filtered listing markers
  useEffect(() => {
    const group = markersLayerRef.current;
    if (!group) return;

    group.clearLayers();
    markerMapRef.current.clear();

    const shortlistSet = new Set(shortlistIds);

    for (const listing of listings) {
      if (!Number.isFinite(listing.lat) || !Number.isFinite(listing.lng)) {
        continue;
      }

      const tier = getPriceTier(listing, priceThresholds);
      const colors = TIER_COLORS[tier];
      const isSelected = listing.id === selectedId;
      const isHovered = listing.id === hoveredId;
      const isShortlisted = shortlistSet.has(listing.id);

      const icon = createListingIcon(
        colors.fill,
        colors.border,
        isSelected,
        isHovered,
        isShortlisted
      );

      const priceDisplay = formatCurrency(getListingPrice(listing, priceMode));
      const priceSuffix = priceMode === 'perPerson' ? '/person' : '/mo';
      const label = `${priceDisplay}${priceSuffix} · ${listing.address || listing.title}`;

      const marker = L.marker([listing.lat, listing.lng], {
        icon,
        zIndexOffset: isSelected ? 800 : isHovered ? 700 : isShortlisted ? 300 : 100,
      });

      marker.bindTooltip(label, {
        direction: 'top',
        offset: [0, -10],
        className: 'housing-tooltip',
      });

      marker.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        onSelectRef.current(listing.id);
      });

      marker.on('mouseover', () => {
        onHoverRef.current(listing.id);
      });

      marker.on('mouseout', () => {
        onHoverRef.current(null);
      });

      marker.addTo(group);
      markerMapRef.current.set(listing.id, marker);
    }
  }, [
    listings,
    selectedId,
    hoveredId,
    shortlistIds,
    priceMode,
    priceThresholds,
  ]);

  // Fly to listing when requested (e.g. from sidebar click)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !flyToRequest) return;
    const targetZoom = Math.max(map.getZoom(), 15);
    map.flyTo([flyToRequest.lat, flyToRequest.lng], targetZoom, {
      duration: 0.65,
      easeLinearity: 0.25,
    });
  }, [flyToRequest]);

  const handleRecenter = () => {
    mapRef.current?.flyTo(center, 13, { duration: 0.6 });
  };

  const handleFitListings = () => {
    const map = mapRef.current;
    if (!map || listings.length === 0) return;
    const validPoints = listings
      .filter((l) => Number.isFinite(l.lat) && Number.isFinite(l.lng))
      .map((l) => [l.lat, l.lng] as [number, number]);
    if (validPoints.length === 0) return;
    const bounds = L.latLngBounds(validPoints);
    map.fitBounds(bounds, { padding: [56, 56], maxZoom: 15 });
  };

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      {/* Floating top-right map controls */}
      <div
        className={`pointer-events-none absolute top-4 z-[450] flex flex-wrap items-center gap-2 transition-all duration-200 ${
          detailOpen ? 'right-4 md:right-[436px]' : 'right-4'
        }`}
      >
        <button
          type="button"
          onClick={onToggleBoundary}
          disabled={!isochrone}
          title={
            isochrone
              ? 'Toggle 20-minute drive zone around OSU Oval'
              : 'Drive boundary data unavailable'
          }
          className={`pointer-events-auto inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold shadow-sm backdrop-blur-md transition ${
            showBoundary && isochrone
              ? 'border-[#BA0C2F]/30 bg-[#BA0C2F] text-white shadow-[#BA0C2F]/20 hover:bg-[#960925]'
              : 'border-slate-200/90 bg-white/95 text-slate-700 hover:bg-white'
          } disabled:cursor-not-allowed disabled:opacity-50`}
        >
          <Layers className="h-3.5 w-3.5" />
          <span>20m Drive Zone</span>
        </button>

        <button
          type="button"
          onClick={handleFitListings}
          disabled={listings.length === 0}
          title="Fit all matching listings in view"
          className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full border border-slate-200/90 bg-white/95 px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm backdrop-blur-md transition hover:bg-white hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Maximize2 className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Fit Results</span>
        </button>

        <button
          type="button"
          onClick={handleRecenter}
          title="Center map on OSU Oval"
          className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full border border-slate-200/90 bg-white/95 px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm backdrop-blur-md transition hover:bg-white hover:text-[#BA0C2F]"
        >
          <Compass className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">OSU Oval</span>
        </button>
      </div>

      {/* Compact price tier legend (bottom-left of visible map area) */}
      <div
        className={`pointer-events-none absolute bottom-6 z-[450] transition-all duration-200 ${
          sidebarOpen ? 'left-4 md:left-4' : 'left-4'
        }`}
      >
        <div className="pointer-events-auto flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-slate-200/90 bg-white/92 px-3 py-2 text-[11px] font-medium text-slate-600 shadow-sm backdrop-blur-md">
          <span className="font-semibold text-slate-800">Per Person:</span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#059669] ring-1 ring-white" />
            <span>≤{formatCurrency(priceThresholds.low)}</span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#D97706] ring-1 ring-white" />
            <span>
              {formatCurrency(priceThresholds.low + 1)}–{formatCurrency(priceThresholds.high)}
            </span>
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full bg-[#BA0C2F] ring-1 ring-white" />
            <span>&gt;{formatCurrency(priceThresholds.high)}</span>
          </span>
          <span className="inline-flex items-center gap-1 border-l border-slate-200 pl-2.5 text-amber-700">
            <span className="inline-flex h-3.5 w-3.5 items-center justify-center rounded-full bg-amber-500 text-[9px] font-bold text-white">
              ★
            </span>
            <span>Shortlisted</span>
          </span>
        </div>
      </div>
    </div>
  );
}
