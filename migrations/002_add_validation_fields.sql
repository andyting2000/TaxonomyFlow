-- Migration: Add validation fields to extracted_data_items table
-- Date: 2025-10-16
-- Description: Adds calculation validation support with warnings storage

-- Add validation_warnings column (stores JSON array of warning objects)
ALTER TABLE extracted_data_items
ADD COLUMN IF NOT EXISTS validation_warnings TEXT;

-- Add has_calculation_warning column (boolean flag for quick filtering)
ALTER TABLE extracted_data_items
ADD COLUMN IF NOT EXISTS has_calculation_warning BOOLEAN DEFAULT FALSE;

-- Create index for filtering items with warnings
CREATE INDEX IF NOT EXISTS idx_validation_warnings
ON extracted_data_items(has_calculation_warning);

-- Update existing rows to have default values
UPDATE extracted_data_items
SET has_calculation_warning = FALSE
WHERE has_calculation_warning IS NULL;

-- Add comment to document the columns
COMMENT ON COLUMN extracted_data_items.validation_warnings IS
'JSON array of validation warning objects from calculation linkbase validation';

COMMENT ON COLUMN extracted_data_items.has_calculation_warning IS
'Quick flag to identify items with calculation validation warnings';
