import React from "react";
import {
  AlertTriangle,
  FileText,
  Globe,
  Landmark,
  Link as LinkIcon,
  Mail,
  MapPin,
  Phone,
  Skull,
  User,
} from "lucide-react";

interface PlatformIconProps {
  platform?: string | null;
  entityType?: string | null;
  value?: string | null;
  className?: string;
}

export const PlatformIcon = React.memo(function PlatformIcon({
  platform,
  entityType,
  value,
  className = "w-5 h-5",
}: PlatformIconProps) {
  const p = (platform || "").toLowerCase();
  const v = (value || "").toLowerCase();
  const t = (entityType || "").toLowerCase();

  // 1. Specific Brands / Platforms matching img-referencia-mapa.png
  if (p.includes("github") || v.includes("github.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path fillRule="evenodd" clipRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" />
      </svg>
    );
  }

  if (p.includes("gitlab") || v.includes("gitlab.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M22.65 14.39L12 22.13 1.35 14.39a.84.84 0 0 1-.3-.94l1.22-3.78 2.44-7.51A.42.42 0 0 1 5.5 2a.43.43 0 0 1 .4.27l2.45 7.51h7.3l2.45-7.51A.42.42 0 0 1 18.5 2a.43.43 0 0 1 .4.27l2.44 7.51L22.95 13.45a.84.84 0 0 1-.3.94z" />
      </svg>
    );
  }

  if (p.includes("twitter") || p.includes("x_twitter") || p === "x" || v.includes("x.com") || v.includes("twitter.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
      </svg>
    );
  }

  if (p.includes("instagram") || v.includes("instagram.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect width="20" height="20" x="2" y="2" rx="5" ry="5" />
        <path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z" />
        <line x1="17.5" x2="17.51" y1="6.5" y2="6.5" />
      </svg>
    );
  }

  if (p.includes("reddit") || v.includes("reddit.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.702zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z" />
      </svg>
    );
  }

  if (p.includes("linkedin") || v.includes("linkedin.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
      </svg>
    );
  }

  if (p.includes("youtube") || v.includes("youtube.com") || v.includes("youtu.be")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z" />
      </svg>
    );
  }

  if (p.includes("discord") || v.includes("discord.gg") || v.includes("discord.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.929 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.893.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z" />
      </svg>
    );
  }

  if (p.includes("stackoverflow") || p.includes("stack overflow") || v.includes("stackoverflow.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M15.725 0l-1.72 1.277 6.39 8.588 1.716-1.277L15.725 0zm-3.94 4.418l-1.377 1.638 8.973 7.545 1.377-1.638-8.973-7.545zm-2.52 5.66l-.97 1.905 11.233 5.727.97-1.905L9.265 10.08zm-1.39 6.26l-.42 2.085 12.33 2.483.42-2.085-12.33-2.483zm-1.875 5.66v-2h13v2h-13zm-2 2h17V17h2v9H2v-9h2v7z" />
      </svg>
    );
  }

  if (p.includes("dev.to") || p === "dev" || v.includes("dev.to")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M7.42 10.05c-.18-.16-.46-.23-.84-.23H5.34v4.36h1.24c.38 0 .66-.07.84-.23.18-.16.27-.42.27-.78v-2.34c0-.36-.09-.62-.27-.78zm1.88.78c0 .76-.23 1.35-.69 1.76-.46.41-1.12.62-1.99.62H4.13V8.61h2.49c.87 0 1.53.21 1.99.62.46.41.69 1 .69 1.6zM13.2 8.61h-3.9v6.78h3.9v-1.21h-2.69v-1.58h2.39v-1.21h-2.39V9.82h2.69V8.61zm4.8 0h-1.31l-1.4 4.54-1.4-4.54h-1.31l2.05 6.78h1.31l2.06-6.78zM24 12c0 6.627-5.373 12-12 12S0 18.627 0 12 5.373 0 12 0s12 5.373 12 12z" />
      </svg>
    );
  }

  if (p.includes("gravatar") || v.includes("gravatar.com")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 0C5.373 0 0 5.373 0 12s5.373 12 12 12 12-5.373 12-12S18.627 0 12 0zm0 2.182c5.422 0 9.818 4.396 9.818 9.818 0 5.422-4.396 9.818-9.818 9.818-5.422 0-9.818-4.396-9.818-9.818 0-5.422 4.396-9.818 9.818-9.818zm0 3.273a6.545 6.545 0 100 13.09 6.545 6.545 0 000-13.09zm0 2.182a4.364 4.364 0 110 8.728 4.364 4.364 0 010-8.728z" />
      </svg>
    );
  }

  if (p.includes("cloudflare") || v.includes("cloudflare")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M19.41 12.58A6.99 6.99 0 0 0 12.5 7a7.02 7.02 0 0 0-6.85 5.58A5.5 5.5 0 0 0 6 23.5h13a5 5 0 0 0 .41-9.92z" />
      </svg>
    );
  }

  if (p.includes("netlify") || v.includes("netlify")) {
    return (
      <svg className={className} viewBox="0 0 24 24" fill="currentColor">
        <path d="M6.49 19.51L12 14.88l5.51 4.63-1.63 2.82H8.12l-1.63-2.82zm11.75-3.03l-4.74-4 4.74-4 3.76 2.17v3.66l-3.76 2.17zM12 9.12l5.51-4.63-1.63-2.82H8.12L6.49 4.49 12 9.12zM5.76 16.48l-3.76-2.17v-3.66l3.76-2.17 4.74 4-4.74 4z" />
      </svg>
    );
  }

  // 2. Specialized OSINT Entity Types
  if (t === "email" || v.includes("@")) {
    return <Mail className={className} />;
  }

  if (t === "domain" || p.includes("domain") || p.includes("portfolio")) {
    return <Globe className={className} />;
  }

  if (t === "document" || p.includes("pdf") || v.endsWith(".pdf")) {
    return <FileText className={className} />;
  }

  if (t === "academic" || p.includes("universidad") || p.includes("unt") || v.includes("unt") || p.includes("scholar") || p.includes("orcid")) {
    return <Landmark className={className} />;
  }

  if (p.includes("trujillo") || p.includes("location") || p.includes("ubicación") || v.includes("trujillo") || v.includes("perú")) {
    return <MapPin className={className} />;
  }

  if (t === "breach" || t === "data_leak") {
    return <AlertTriangle className={className} />;
  }

  if (t === "infostealer") {
    return <Skull className={className} />;
  }

  if (t === "phone") {
    return <Phone className={className} />;
  }

  if (t === "person" || t === "target") {
    return <User className={className} />;
  }

  if (p.includes("portfolio") || p.includes("enlace") || p.includes("link")) {
    return <LinkIcon className={className} />;
  }

  // Default fallback
  return <Globe className={className} />;
});
