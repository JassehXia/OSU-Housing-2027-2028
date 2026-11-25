import { useState } from 'react';
import {
  Check,
  Copy,
  ExternalLink,
  Heart,
  MapPin,
  Trash2,
  X,
} from 'lucide-react';
import type { Listing } from '../types/housing';
import {
  buildShortlistSummary,
  formatCurrency,
  formatDriveWalk,
} from '../utils/format';

interface ShortlistModalProps {
  open: boolean;
  listings: Listing[];
  notes: Record<string, string>;
  onClose: () => void;
  onSelectListing: (listing: Listing) => void;
  onRemoveShortlist: (id: string) => void;
  onChangeNote: (id: string, note: string) => void;
}

export function ShortlistModal({
  open,
  listings,
  notes,
  onClose,
  onSelectListing,
  onRemoveShortlist,
  onChangeNote,
}: ShortlistModalProps) {
  const [copied, setCopied] = useState(false);

  if (!open) return null;

  const handleCopySummary = async () => {
    const text = buildShortlistSummary(listings, notes);
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2200);
    } catch {
      // Fallback for restricted clipboard contexts
      const textarea = document.createElement('textarea');
      textarea.value = text;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      document.body.removeChild(textarea);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2200);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[700] flex items-center justify-center bg-slate-900/45 p-4 backdrop-blur-xs"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-5 py-4">
          <div className="flex items-center gap-2.5">
            <span className="inline-flex h-8 w-8 items-center justify-center rounded-xl bg-[#FDF2F4] text-[#BA0C2F]">
              <Heart className="h-4 w-4 fill-[#BA0C2F]" />
            </span>
            <div>
              <h2 className="text-base font-bold text-slate-900">
                Shortlisted 4-Bed Homes ({listings.length})
              </h2>
              <p className="text-xs text-slate-500">
                Compare favorites, edit roommate notes, and copy a summary for your group chat.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close shortlist"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 thin-scrollbar">
          {listings.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-200 bg-slate-50 py-12 text-center">
              <Heart className="h-8 w-8 text-slate-300" />
              <p className="mt-2 text-sm font-semibold text-slate-700">
                Your shortlist is empty
              </p>
              <p className="mt-1 max-w-xs text-xs text-slate-500">
                Click the heart icon on any 4-bedroom listing to save it here and compare with your roommates.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {listings.map((listing) => (
                <div
                  key={listing.id}
                  className="rounded-xl border border-slate-200 bg-slate-50/50 p-3.5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-2">
                        <h3 className="text-sm font-bold text-slate-900">
                          {listing.address || listing.title}
                        </h3>
                        <span className="text-xs font-bold text-[#BA0C2F]">
                          {formatCurrency(listing.rentPerPerson)}/person
                        </span>
                        <span className="text-xs text-slate-500">
                          ({formatCurrency(listing.rentTotal)}/mo)
                        </span>
                      </div>
                      <p className="mt-0.5 text-xs text-slate-500">
                        {listing.bedrooms} bd
                        {listing.bathrooms != null ? ` · ${listing.bathrooms} ba` : ''}
                        {listing.sqft != null ? ` · ${listing.sqft.toLocaleString()} sqft` : ''}
                        {' · '}
                        {formatDriveWalk(listing)}
                        {listing.landlord ? ` · ${listing.landlord}` : ''}
                      </p>
                    </div>

                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => {
                          onSelectListing(listing);
                          onClose();
                        }}
                        className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 transition hover:border-[#BA0C2F]/40 hover:text-[#BA0C2F]"
                      >
                        <MapPin className="h-3.5 w-3.5" />
                        <span>Locate</span>
                      </button>

                      {listing.url && (
                        <a
                          href={listing.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-600 transition hover:text-[#BA0C2F]"
                          title="Open original listing"
                        >
                          <ExternalLink className="h-3.5 w-3.5" />
                        </a>
                      )}

                      <button
                        type="button"
                        onClick={() => onRemoveShortlist(listing.id)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-400 transition hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600"
                        title="Remove from shortlist"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>

                  <textarea
                    rows={2}
                    value={notes[listing.id] ?? ''}
                    onChange={(e) => onChangeNote(listing.id, e.target.value)}
                    placeholder="Add roommate notes for this property..."
                    className="mt-2.5 w-full resize-none rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs text-slate-800 placeholder:text-slate-400 focus:border-[#BA0C2F]/50 focus:outline-none"
                  />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50/70 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-200 bg-white px-3.5 py-2 text-xs font-semibold text-slate-700 transition hover:bg-slate-100"
          >
            Close
          </button>

          <button
            type="button"
            disabled={listings.length === 0}
            onClick={handleCopySummary}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#BA0C2F] px-4 py-2 text-xs font-semibold text-white shadow-xs transition hover:bg-[#960925] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5" />
                <span>Copied for Group Chat!</span>
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5" />
                <span>Copy Summary for Group Chat</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
