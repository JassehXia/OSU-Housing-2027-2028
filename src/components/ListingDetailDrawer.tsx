import { useEffect, useState } from 'react';
import {
  Bath,
  BedDouble,
  Building2,
  Calendar,
  Car,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Footprints,
  Heart,
  Home,
  MapPin,
  PawPrint,
  Ruler,
  StickyNote,
  X,
} from 'lucide-react';
import type { Listing } from '../types/housing';
import { formatCurrency, getPriceTier, TIER_COLORS } from '../utils/format';

interface ListingDetailDrawerProps {
  listing: Listing | null;
  priceThresholds: { low: number; high: number };
  isShortlisted: boolean;
  note: string;
  onClose: () => void;
  onToggleShortlist: (id: string) => void;
  onChangeNote: (id: string, note: string) => void;
}

export function ListingDetailDrawer({
  listing,
  priceThresholds,
  isShortlisted,
  note,
  onClose,
  onToggleShortlist,
  onChangeNote,
}: ListingDetailDrawerProps) {
  const [photoIdx, setPhotoIdx] = useState(0);
  const [failedPhotos, setFailedPhotos] = useState<Record<number, boolean>>({});
  const [savedPulse, setSavedPulse] = useState(false);

  useEffect(() => {
    setPhotoIdx(0);
    setFailedPhotos({});
  }, [listing?.id]);

  if (!listing) return null;

  const photos = listing.photos ?? [];
  const hasPhotos = photos.length > 0 && !failedPhotos[photoIdx];
  const tier = getPriceTier(listing, priceThresholds);
  const tierStyle = TIER_COLORS[tier];

  const handlePrevPhoto = () => {
    setPhotoIdx((prev) => (prev - 1 + photos.length) % photos.length);
  };

  const handleNextPhoto = () => {
    setPhotoIdx((prev) => (prev + 1) % photos.length);
  };

  const handleNoteChange = (value: string) => {
    onChangeNote(listing.id, value);
    setSavedPulse(true);
    window.setTimeout(() => setSavedPulse(false), 1200);
  };

  return (
    <section
      aria-label="Listing details"
      className="fixed top-0 right-0 z-[550] flex h-full w-full max-w-[420px] flex-col border-l border-slate-200/90 bg-white shadow-2xl"
    >
      {/* Top Bar */}
      <div className="flex items-center justify-between border-b border-slate-200/80 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-semibold ${tierStyle.badgeBg} ${tierStyle.badgeText}`}
          >
            {tierStyle.label}
          </span>
          {listing.source && (
            <span className="truncate text-xs font-medium text-slate-400">
              via {listing.source}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close listing details"
          className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-500 transition hover:bg-slate-100 hover:text-slate-800"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Scrollable Body */}
      <div className="flex-1 overflow-y-auto thin-scrollbar">
        {/* Photo Carousel */}
        <div className="relative h-56 w-full bg-slate-100">
          {hasPhotos ? (
            <img
              src={photos[photoIdx]}
              alt={`${listing.address || listing.title} — photo ${photoIdx + 1}`}
              className="h-full w-full object-cover"
              onError={() =>
                setFailedPhotos((prev) => ({ ...prev, [photoIdx]: true }))
              }
            />
          ) : (
            <div className="flex h-full w-full flex-col items-center justify-center bg-gradient-to-br from-slate-100 via-slate-50 to-slate-200 text-slate-400">
              <Home className="h-10 w-10 text-slate-300" />
              <span className="mt-2 text-xs font-medium text-slate-400">
                No property photo available
              </span>
            </div>
          )}

          {photos.length > 1 && (
            <>
              <button
                type="button"
                onClick={handlePrevPhoto}
                aria-label="Previous photo"
                className="absolute top-1/2 left-2.5 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full bg-slate-900/60 text-white backdrop-blur-xs transition hover:bg-slate-900/80"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={handleNextPhoto}
                aria-label="Next photo"
                className="absolute top-1/2 right-2.5 inline-flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full bg-slate-900/60 text-white backdrop-blur-xs transition hover:bg-slate-900/80"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
              <span className="absolute right-3 bottom-2.5 rounded-full bg-slate-900/70 px-2.5 py-0.5 text-[11px] font-semibold text-white backdrop-blur-xs">
                {photoIdx + 1} / {photos.length}
              </span>
            </>
          )}
        </div>

        <div className="space-y-5 p-4">
          {/* Price & Address Header */}
          <div>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="text-2xl font-bold tracking-tight text-slate-900">
                {formatCurrency(listing.rentTotal)}
                <span className="text-sm font-medium text-slate-500">/mo total</span>
              </span>
              <span className="text-sm font-semibold text-[#BA0C2F]">
                · {formatCurrency(listing.rentPerPerson)}/person
              </span>
            </div>

            <h2 className="mt-1.5 text-base font-bold text-slate-900">
              {listing.address || listing.title}
            </h2>
            {listing.title && listing.title !== listing.address && (
              <p className="mt-0.5 text-xs text-slate-500">{listing.title}</p>
            )}
            {listing.neighborhood && (
              <p className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-slate-600">
                <MapPin className="h-3.5 w-3.5 text-[#BA0C2F]" />
                <span>{listing.neighborhood}</span>
              </p>
            )}
          </div>

          {/* Primary Action Buttons */}
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => onToggleShortlist(listing.id)}
              className={`inline-flex items-center justify-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition ${
                isShortlisted
                  ? 'border-[#BA0C2F] bg-[#FDF2F4] text-[#BA0C2F]'
                  : 'border-slate-200 bg-white text-slate-700 hover:border-slate-300 hover:bg-slate-50'
              }`}
            >
              <Heart
                className={`h-4 w-4 ${isShortlisted ? 'fill-[#BA0C2F] text-[#BA0C2F]' : ''}`}
              />
              <span>{isShortlisted ? 'Shortlisted' : 'Add to Shortlist'}</span>
            </button>

            {listing.url ? (
              <a
                href={listing.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-[#BA0C2F] px-3 py-2 text-xs font-semibold text-white shadow-xs transition hover:bg-[#960925]"
              >
                <span>View Original Listing</span>
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            ) : (
              <span className="inline-flex items-center justify-center rounded-xl bg-slate-100 px-3 py-2 text-xs font-medium text-slate-400">
                No External Link
              </span>
            )}
          </div>

          {/* Key Specs Grid */}
          <div className="grid grid-cols-3 gap-2 rounded-xl border border-slate-200/80 bg-slate-50/70 p-3 text-center">
            <div>
              <div className="flex items-center justify-center gap-1 text-slate-400">
                <BedDouble className="h-3.5 w-3.5" />
              </div>
              <p className="mt-1 text-sm font-bold text-slate-900">
                {listing.bedrooms} bd
              </p>
              <p className="text-[11px] text-slate-500">Bedrooms</p>
            </div>
            <div className="border-x border-slate-200/80">
              <div className="flex items-center justify-center gap-1 text-slate-400">
                <Bath className="h-3.5 w-3.5" />
              </div>
              <p className="mt-1 text-sm font-bold text-slate-900">
                {listing.bathrooms != null ? `${listing.bathrooms} ba` : '—'}
              </p>
              <p className="text-[11px] text-slate-500">Bathrooms</p>
            </div>
            <div>
              <div className="flex items-center justify-center gap-1 text-slate-400">
                <Ruler className="h-3.5 w-3.5" />
              </div>
              <p className="mt-1 text-sm font-bold text-slate-900">
                {listing.sqft != null ? listing.sqft.toLocaleString() : '—'}
              </p>
              <p className="text-[11px] text-slate-500">Sq. Ft.</p>
            </div>
          </div>

          {/* Commute to OSU Oval */}
          <div className="grid grid-cols-2 gap-2">
            <div className="flex items-center gap-2.5 rounded-xl border border-slate-200/80 bg-white p-2.5">
              <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                <Car className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <p className="text-xs font-bold text-slate-900">
                  {listing.driveMinutes != null
                    ? `${Math.round(listing.driveMinutes)} min drive`
                    : '—'}
                </p>
                <p className="text-[11px] text-slate-500">
                  {listing.distanceMiles != null
                    ? `${listing.distanceMiles.toFixed(1)} mi to Oval`
                    : 'To OSU Oval'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2.5 rounded-xl border border-slate-200/80 bg-white p-2.5">
              <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-700">
                <Footprints className="h-4 w-4" />
              </span>
              <div className="min-w-0">
                <p className="text-xs font-bold text-slate-900">
                  {listing.walkMinutes != null
                    ? `${Math.round(listing.walkMinutes)} min walk`
                    : '—'}
                </p>
                <p className="text-[11px] text-slate-500">To OSU Oval</p>
              </div>
            </div>
          </div>

          {/* Property Details */}
          <div className="space-y-2.5 rounded-xl border border-slate-200/80 bg-white p-3.5 text-xs">
            <div className="flex items-start gap-2.5">
              <Building2 className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              <div className="min-w-0 flex-1">
                <span className="text-slate-500">Landlord: </span>
                <span className="font-semibold text-slate-800">
                  {listing.landlord || 'Not listed'}
                </span>
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <Calendar className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              <div className="min-w-0 flex-1">
                <span className="text-slate-500">Availability: </span>
                <span className="font-semibold text-slate-800">
                  {listing.availableDate || 'Contact landlord'}
                </span>
                {listing.leaseTerm && (
                  <span className="text-slate-500"> · {listing.leaseTerm}</span>
                )}
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <Car className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              <div className="min-w-0 flex-1">
                <span className="text-slate-500">Parking: </span>
                <span className="font-semibold text-slate-800">
                  {listing.parking || 'Not specified'}
                </span>
              </div>
            </div>

            <div className="flex items-start gap-2.5">
              <PawPrint className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
              <div className="min-w-0 flex-1">
                <span className="text-slate-500">Pets: </span>
                <span className="font-semibold text-slate-800">
                  {listing.petPolicy
                    ? listing.petPolicy
                    : listing.petsAllowed === true
                      ? 'Pets allowed'
                      : listing.petsAllowed === false
                        ? 'No pets'
                        : 'Not specified'}
                </span>
              </div>
            </div>
          </div>

          {/* Amenities */}
          {listing.amenities && listing.amenities.length > 0 && (
            <div>
              <h3 className="mb-2 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                Amenities
              </h3>
              <div className="flex flex-wrap gap-1.5">
                {listing.amenities.map((amenity) => (
                  <span
                    key={amenity}
                    className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-medium text-slate-700"
                  >
                    {amenity}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Description */}
          {listing.description && (
            <div>
              <h3 className="mb-1.5 text-xs font-semibold tracking-wide text-slate-500 uppercase">
                Description
              </h3>
              <p className="text-xs leading-relaxed whitespace-pre-line text-slate-600">
                {listing.description}
              </p>
            </div>
          )}

          {/* Roommate Notes (saved in localStorage) */}
          <div className="rounded-xl border border-amber-200/80 bg-amber-50/40 p-3.5">
            <div className="mb-1.5 flex items-center justify-between">
              <label
                htmlFor="roommate-notes"
                className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-800"
              >
                <StickyNote className="h-3.5 w-3.5 text-amber-600" />
                <span>Roommate Notes</span>
              </label>
              <span
                className={`inline-flex items-center gap-1 text-[11px] font-medium transition-opacity ${
                  savedPulse ? 'text-emerald-600 opacity-100' : 'text-slate-400 opacity-80'
                }`}
              >
                {savedPulse ? (
                  <>
                    <Check className="h-3 w-3" />
                    <span>Saved</span>
                  </>
                ) : (
                  <span>Auto-saved locally</span>
                )}
              </span>
            </div>
            <textarea
              id="roommate-notes"
              rows={3}
              value={note}
              onChange={(e) => handleNoteChange(e.target.value)}
              placeholder="Add pros/cons, tour time, parking details, roommate votes..."
              className="w-full resize-none rounded-lg border border-amber-200 bg-white px-2.5 py-2 text-xs text-slate-800 placeholder:text-slate-400 focus:border-[#BA0C2F]/50 focus:ring-2 focus:ring-[#BA0C2F]/15 focus:outline-none"
            />
          </div>
        </div>
      </div>
    </section>
  );
}
