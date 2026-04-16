import * as React from "react";
import { cva } from "class-variance-authority";
import { cn } from "../../lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap text-sm font-bold font-headline uppercase tracking-widest transition-all focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow hover:shadow-accent-sm hover:scale-[1.02] active:scale-95",
        destructive:
          "bg-[#93000a] text-[#ffdad6] shadow-sm hover:bg-[#93000a]/90",
        outline:
          "border border-[#514534]/30 bg-transparent hover:border-primary-container/50 hover:bg-[#1d1b1a] text-[#d6c4ae]",
        secondary:
          "border border-[#514534]/30 bg-transparent text-[#d6c4ae] hover:border-primary-container/50 hover:bg-[#1d1b1a]",
        ghost:
          "text-[#d6c4ae] hover:bg-[#1d1b1a] hover:text-[#F5F0E8]",
        link: "text-primary-container underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-6 py-2",
        sm: "h-8 px-4 text-xs",
        lg: "h-12 px-10 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

const Button = React.forwardRef(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
