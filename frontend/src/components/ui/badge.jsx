import * as React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils";

const badgeVariants = cva(
  "inline-flex items-center border px-2.5 py-0.5 text-xs font-bold font-headline uppercase tracking-wider transition-colors focus:outline-none focus:ring-2 focus:ring-[#E8A020] focus:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-[#E8A020] text-[#442b00] shadow",
        secondary:
          "border-[#514534]/30 bg-[#1d1b1a] text-[#d6c4ae]",
        destructive:
          "border-transparent bg-[#93000a] text-[#ffdad6] shadow",
        outline: "text-[#F5F0E8] border-[#514534]/30",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

function Badge({ className, variant, ...props }) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
