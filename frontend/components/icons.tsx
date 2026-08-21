import type { SVGProps } from "react";

function Icon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    />
  );
}

export function HomeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M3 9.5L10 3.5L17 9.5" />
      <path d="M5 8v8.5h10V8" />
    </Icon>
  );
}

export function GridIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x="3" y="3" width="6" height="6" rx="1" />
      <rect x="11" y="3" width="6" height="6" rx="1" />
      <rect x="3" y="11" width="6" height="6" rx="1" />
      <rect x="11" y="11" width="6" height="6" rx="1" />
    </Icon>
  );
}

export function FolderIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M3 5.5a1 1 0 0 1 1-1h4l1.5 2H16a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />
    </Icon>
  );
}

export function PlayListIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M4 5.5h10" />
      <path d="M4 10h10" />
      <path d="M4 14.5h6" />
      <path d="M14.5 12.5l3 2-3 2z" fill="currentColor" stroke="none" />
    </Icon>
  );
}

export function PackageIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M10 3l6.5 3.5v7L10 17l-6.5-3.5v-7z" />
      <path d="M3.5 6.5L10 10l6.5-3.5" />
      <path d="M10 10v7" />
    </Icon>
  );
}

export function GearIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <circle cx="10" cy="10" r="2.6" />
      <path d="M10 3.3v1.8M10 14.9v1.8M16.7 10h-1.8M5.1 10H3.3M14.7 5.3l-1.3 1.3M6.6 13.4l-1.3 1.3M14.7 14.7l-1.3-1.3M6.6 6.6L5.3 5.3" />
    </Icon>
  );
}

export function MenuIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M3.5 5.5h13" />
      <path d="M3.5 10h13" />
      <path d="M3.5 14.5h13" />
    </Icon>
  );
}

export function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M5 5l10 10M15 5L5 15" />
    </Icon>
  );
}

export function ChevronLeftIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M12 4.5L6.5 10l5.5 5.5" />
    </Icon>
  );
}

export function ChevronRightIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M8 4.5L13.5 10L8 15.5" />
    </Icon>
  );
}

export function PaperclipIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M13.5 6.5L7.6 12.4a2.3 2.3 0 0 0 3.25 3.25l6.4-6.4a4 4 0 0 0-5.66-5.66l-6.4 6.4a5.7 5.7 0 0 0 8.06 8.06" />
    </Icon>
  );
}

export function MicIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <rect x="7.5" y="2.5" width="5" height="9" rx="2.5" />
      <path d="M5 10a5 5 0 0 0 10 0" />
      <path d="M10 15v3" />
      <path d="M7 18h6" />
    </Icon>
  );
}

export function FileIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <Icon {...props}>
      <path d="M6 2.5h5.5L15 6v11.5H6z" />
      <path d="M11.5 2.5V6H15" />
    </Icon>
  );
}
