// static/js/api.js - API Communication Module

export class APIClient {
    constructor(baseURL = '/api/v1') {
        this.baseURL = baseURL;
    }

    /**
     * Generic API call with error handling
     */
    async call(endpoint, options = {}) {
        const url = `${this.baseURL}${endpoint}`;
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
            },
        };
        
        const finalOptions = { ...defaultOptions, ...options };
        
        try {
            const response = await fetch(url, finalOptions);
            
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({ error: 'Request failed' }));
                throw new Error(errorData.error || `HTTP ${response.status}`);
            }
            
            return await response.json();
        } catch (error) {
            console.error(`API call failed: ${endpoint}`, error);
            throw error;
        }
    }

    // Job Management
    async getJobs(limit = 50) {
        return this.call(`/filings/jobs?limit=${limit}`);
    }

    async getJob(jobId) {
        return this.call(`/filings/jobs/${jobId}`);
    }

    async getJobStatus(jobId) {
        return this.call(`/filings/jobs/${jobId}/status`);
    }

    async getJobPages(jobId) {
        return this.call(`/filings/jobs/${jobId}/pages`);
    }

    async getPages(jobId) {
        return this.call(`/filings/jobs/${jobId}/pages`);
    }

    async getExtractedData(jobId, page = 1, size = 1000) {
        return this.call(`/filings/jobs/${jobId}/extracted-data?page=${page}&size=${size}`);
    }

    // Dashboard Stats
    async getDashboardStats() {
        return this.call('/filings/dashboard/stats');
    }

    async getProcessingJobs() {
        return this.call('/jobs/processing');
    }

    // Data Management
    async createExtractedItem(pageId, itemData) {
        return this.call(`/filings/extracted-data/create?page_id=${pageId}`, {
            method: 'POST',
            body: JSON.stringify(itemData)
        });
    }

    async createExtractedDataItem(itemData) {
        // Extract page_id from itemData
        const { page_id, ...data } = itemData;
        return this.call(`/filings/extracted-data/create?page_id=${page_id}`, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }

    async bulkUpdateItems(items) {
        return this.call('/filings/extracted-data/bulk-update', {
            method: 'PUT',
            body: JSON.stringify({ items })
        });
    }

    async deleteItem(itemId) {
        return this.call(`/filings/extracted-data/${itemId}`, {
            method: 'DELETE'
        });
    }

    // Taxonomy Search
    async searchTaxonomy(query) {
        const url = `/taxonomy/search?q=${encodeURIComponent(query)}`;
        return fetch(`${this.baseURL}${url}`).then(res => res.json());
    }

    async getTaxonomyStatus() {
        return this.call('/taxonomy/status');
    }

    // File Upload
    async uploadFile(formData) {
        // Don't set Content-Type header for FormData
        return fetch(`${this.baseURL}/filings/upload`, {
            method: 'POST',
            body: formData
        }).then(async (response) => {
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Upload failed');
            }
            return response.json();
        });
    }

    // XBRL Generation
    getXBRLDownloadURL(jobId) {
        return `${this.baseURL}/filings/jobs/${jobId}/download-xbrl`;
    }

    async validateXBRL(jobId) {
        return this.call(`/filings/jobs/${jobId}/validate-xbrl`);
    }
}

// Export singleton instance
export const api = new APIClient();
