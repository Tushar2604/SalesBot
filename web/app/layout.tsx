import type { Metadata } from "next";
import "./globals.css";
import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = {
  title: "SalesBot",
  description: "LinkedIn and email outreach automation",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
