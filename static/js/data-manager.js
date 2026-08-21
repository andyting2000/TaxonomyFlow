// static/js/data-manager.js - Data Management and State

export class DataManager {
    constructor(api, notifications) {
        this.api = api;
        this.notifications = notifications;

        // State
        this.currentJob = null;
        this.currentPageNumber = 1;
        this.totalPages = 0;
        this.currentPageData = null;
        this.pendingChanges = new Set();
    }

    /**
     * Load job by ID
     */
    async loadJob(jobId) {
        try {
            const job = await this.api.getJob(jobId);
            this.currentJob = job;
            this.currentPageNumber = 1; // Reset to first page
            return job;
        } catch (error) {
            console.error('Failed to load job:', error);
            throw error;
        }
    }

    /**
     * Load pages for current job
     */
    async loadPages() {
        if (!this.currentJob) {
            throw new Error('No job selected');
        }

        const pages = await this.api.getJobPages(this.currentJob.id);
        this.totalPages = pages.length;
        return pages;
    }

    /**
     * Load extracted data for current page
     */
    async loadCurrentPageData() {
        if (!this.currentJob) {
            throw new Error('No job selected');
        }

        // Get all extracted data
        const data = await this.api.getExtractedData(this.currentJob.id, 1, 1000);

        // Filter items for the current page only
        const pageItems = data.items.filter(item => item.page_number === this.currentPageNumber);
        this.currentPageData = pageItems;

        return {
            items: pageItems,
            total: pageItems.length
        };
    }

    /**
     * Get current page image URL
     */
    getCurrentPageImageUrl() {
        if (!this.currentJob) return null;
        return `/filings/jobs/${this.currentJob.id}/pages/${this.currentPageNumber}/image`;
    }

    /**
     * Create new item
     */
    async createItem(pageId, itemData) {
        try {
            const newItem = await this.api.createExtractedItem(pageId, itemData);
            this.notifications.success('Item created successfully');
            return newItem;
        } catch (error) {
            console.error('Failed to create item:', error);
            this.notifications.error('Failed to create item');
            throw error;
        }
    }

    /**
     * Track pending changes
     */
    trackChange(itemId) {
        this.pendingChanges.add(itemId);
    }

    /**
     * Check if there are pending changes
     */
    hasPendingChanges() {
        return this.pendingChanges.size > 0;
    }

    /**
     * Clear pending changes
     */
    clearPendingChanges() {
        this.pendingChanges.clear();
    }

    /**
     * Collect changes from form rows
     */
    collectChanges() {
        const validChanges = [];
        const deletedIds = [];

        for (const itemId of this.pendingChanges) {
            const row = document.querySelector(`[data-item-id="${itemId}"]`);

            // If row doesn't exist or is marked for deletion
            if (!row || row.style.opacity === '0.5') {
                if (!itemId.toString().startsWith('new_')) {
                    deletedIds.push(itemId);
                }
                continue;
            }

            // Row exists and is valid, collect its data
            const isNew = row.dataset.isNew === 'true';
            const itemData = {
                id: itemId,
                isNew: isNew
            };

            // Collect all field values
            const fields = row.querySelectorAll('[data-field]');
            fields.forEach(field => {
                const fieldName = field.dataset.field;

                if (fieldName === 'is_reviewed') {
                    itemData[fieldName] = field.checked;
                } else if (fieldName === 'confirmed_tag_id') {
                    // Handle both template field ID and taxonomy tag ID
                    const templateFieldId = field.dataset.templateFieldId;
                    const tagId = field.dataset.tagId;

                    if (templateFieldId) {
                        itemData['template_field_id'] = templateFieldId;
                        itemData['confirmed_tag_id'] = null; // Clear old taxonomy reference
                    } else if (tagId) {
                        itemData[fieldName] = parseInt(tagId);
                        itemData['template_field_id'] = null; // Clear template reference
                    } else {
                        itemData[fieldName] = null;
                        itemData['template_field_id'] = null;
                    }
                } else if (fieldName === 'financial_year') {
                    const year = field.value;
                    itemData[fieldName] = year ? parseInt(year) : null;
                } else {
                    itemData[fieldName] = field.value;
                }
            });

            validChanges.push(itemData);
        }

        return { validChanges, deletedIds };
    }

    /**
     * Save all pending changes
     */
    async saveChanges() {
        if (this.pendingChanges.size === 0) {
            this.notifications.info('No changes to save');
            return { success: true, count: 0 };
        }

        try {
            const { validChanges, deletedIds } = this.collectChanges();
            let totalSaved = 0;

            // Step 1: Delete marked items
            for (const itemId of deletedIds) {
                try {
                    await this.api.deleteItem(itemId);
                    totalSaved++;
                } catch (error) {
                    console.error(`Failed to delete item ${itemId}:`, error);
                }
            }

            // Step 2: Get current page ID for new items
            let currentPageId = null;
            const newItems = validChanges.filter(item => item.isNew);

            if (newItems.length > 0) {
                const pages = await this.api.getJobPages(this.currentJob.id);
                const currentPage = pages[this.currentPageNumber - 1];
                currentPageId = currentPage.id;
            }

            // Step 3: Create new items
            for (const itemData of newItems) {
                try {
                    const payload = {
                        extracted_label: itemData.extracted_label,
                        extracted_value: itemData.extracted_value,
                        financial_year: itemData.financial_year
                    };

                    await this.api.createExtractedItem(currentPageId, payload);
                    totalSaved++;
                } catch (error) {
                    console.error('Failed to create item:', error);
                }
            }

            // Step 4: Update existing items
            const existingItems = validChanges.filter(item => !item.isNew);

            if (existingItems.length > 0) {
                try {
                    const itemsForUpdate = existingItems.map(item => ({
                        id: item.id,
                        extracted_label: item.extracted_label,
                        extracted_value: item.extracted_value,
                        financial_year: item.financial_year,
                        is_reviewed: item.is_reviewed,
                        confirmed_tag_id: item.confirmed_tag_id
                    }));

                    await this.api.bulkUpdateItems(itemsForUpdate);
                    totalSaved += existingItems.length;
                } catch (error) {
                    console.error('Failed to bulk update:', error);
                    throw error;
                }
            }

            // Clear pending changes
            this.clearPendingChanges();

            return { success: true, count: totalSaved };

        } catch (error) {
            console.error('Save failed:', error);
            throw error;
        }
    }

    /**
     * Calculate review statistics
     */
    getReviewStats() {
        const totalRows = document.querySelectorAll('.form-row:not([style*="opacity: 0.5"])').length;
        const reviewedRows = document.querySelectorAll('input[data-field="is_reviewed"]:checked').length;
        const reviewedWithTags = Array.from(document.querySelectorAll('.form-row')).filter(row => {
            const checkbox = row.querySelector('input[data-field="is_reviewed"]');
            const tagInput = row.querySelector('.taxonomy-search-input');
            return checkbox?.checked && tagInput?.dataset.tagId;
        }).length;

        // Template-review UI doesn't use .form-row; count filled template fields as reviewed.
        const templateFilledCount = Array.from(
            document.querySelectorAll('input[data-field-id], textarea[data-field-id], select[data-field-id]')
        ).filter(el => el.value && el.value.trim() !== '').length;

        return {
            total: totalRows || templateFilledCount,
            reviewed: reviewedRows,
            reviewedWithTags: reviewedWithTags || templateFilledCount
        };
    }

    /**
     * Navigate to a specific page
     */
    goToPage(pageNumber) {
        if (pageNumber < 1 || pageNumber > this.totalPages) {
            return false;
        }
        this.currentPageNumber = pageNumber;
        return true;
    }

    /**
     * Get current state summary
     */
    getState() {
        return {
            currentJob: this.currentJob,
            currentPageNumber: this.currentPageNumber,
            totalPages: this.totalPages,
            hasPendingChanges: this.hasPendingChanges(),
            pendingChangesCount: this.pendingChanges.size
        };
    }

    /**
     * Reset state
     */
    reset() {
        this.currentJob = null;
        this.currentPageNumber = 1;
        this.totalPages = 0;
        this.currentPageData = null;
        this.clearPendingChanges();
    }
}
