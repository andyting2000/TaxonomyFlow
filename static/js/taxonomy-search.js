// static/js/taxonomy-search.js - Taxonomy Search Functionality

export class TaxonomySearch {
    constructor(api, onSelectCallback) {
        this.api = api;
        this.onSelectCallback = onSelectCallback;
        this.searchCache = new Map();
        this.taxonomyStatusChecked = false;
    }

    /**
     * Initialize taxonomy search for all inputs on the page
     */
    initializeSearchInputs() {
        const searchInputs = document.querySelectorAll('.taxonomy-search-input');
        
        console.log(`Initializing taxonomy search for ${searchInputs.length} inputs`);
        
        searchInputs.forEach((input, index) => {
            let searchTimeout;
            
            const inputHandler = (e) => {
                clearTimeout(searchTimeout);
                const query = e.target.value.trim();
                
                if (query.length < 2) {
                    this.hideDropdown(input);
                    return;
                }
                
                searchTimeout = setTimeout(() => {
                    this.search(query, input);
                }, 300);
            };
            
            const focusHandler = (e) => {
                const query = e.target.value.trim();
                if (query.length >= 2) {
                    this.search(query, input);
                }
            };
            
            const keydownHandler = (e) => {
                const dropdown = input.parentNode.querySelector('.taxonomy-dropdown');
                if (!dropdown || dropdown.classList.contains('hidden')) return;
                
                if (e.key === 'Escape') {
                    this.hideDropdown(input);
                    e.preventDefault();
                }
            };
            
            // Remove old listeners if they exist
            if (input._boundHandlers) {
                input.removeEventListener('input', input._boundHandlers.input);
                input.removeEventListener('focus', input._boundHandlers.focus);
                input.removeEventListener('keydown', input._boundHandlers.keydown);
            }
            
            // Store bound handlers
            input._boundHandlers = {
                input: inputHandler,
                focus: focusHandler,
                keydown: keydownHandler
            };
            
            // Attach new listeners
            input.addEventListener('input', inputHandler);
            input.addEventListener('focus', focusHandler);
            input.addEventListener('keydown', keydownHandler);
        });
        
        // Global click handler for closing dropdowns
        const clickHandler = (e) => {
            if (!e.target.closest('.taxonomy-search-container')) {
                document.querySelectorAll('.taxonomy-dropdown').forEach(dropdown => {
                    dropdown.classList.add('hidden');
                });
            }
        };
        
        // Remove old global handler if exists
        if (this._taxonomyClickHandler) {
            document.removeEventListener('click', this._taxonomyClickHandler);
        }
        
        this._taxonomyClickHandler = clickHandler;
        document.addEventListener('click', clickHandler);
    }

    /**
     * Search taxonomy tags
     */
    async search(query, inputElement) {
        console.log(`Searching taxonomy for: "${query}"`);
        
        try {
            // Check cache first
            const cacheKey = query.toLowerCase();
            if (this.searchCache.has(cacheKey)) {
                const results = this.searchCache.get(cacheKey);
                this.showDropdown(inputElement, results);
                return;
            }
            
            // Show loading
            this.showDropdown(inputElement, [], true);
            
            // Make API call
            const data = await this.api.searchTaxonomy(query);
            const results = data.results || [];
            
            // Check taxonomy status if no results on first search
            if (results.length === 0 && !this.taxonomyStatusChecked) {
                this.taxonomyStatusChecked = true;
                const statusData = await this.api.getTaxonomyStatus();
                
                if (!statusData.is_loaded) {
                    console.warn('No taxonomy data loaded');
                }
            }
            
            // Cache results
            this.searchCache.set(cacheKey, results);
            
            // Show results
            this.showDropdown(inputElement, results);
            
        } catch (error) {
            console.error('Taxonomy search failed:', error);
            this.hideDropdown(inputElement);
        }
    }

    /**
     * Show dropdown with results
     */
    showDropdown(inputElement, results, isLoading = false) {
        const container = inputElement.parentNode;
        const dropdown = container.querySelector('.taxonomy-dropdown');
        
        if (!dropdown) {
            console.error('Cannot find dropdown element');
            return;
        }
        
        if (isLoading) {
            dropdown.innerHTML = `
                <div class="taxonomy-option flex items-center justify-center py-4">
                    <div class="loading-spinner mr-2"></div>
                    <span class="text-gray-600">Searching...</span>
                </div>
            `;
            dropdown.classList.remove('hidden');
            return;
        }
        
        if (results.length === 0) {
            dropdown.innerHTML = `
                <div class="taxonomy-option text-center py-4">
                    <span class="text-gray-500">🔍 No matching tags found</span>
                </div>
            `;
            dropdown.classList.remove('hidden');
            return;
        }
        
        // Build dropdown HTML
        const dropdownHTML = results.map(tag => {
            const escapedLabel = tag.label.replace(/'/g, "\\'").replace(/"/g, '&quot;');
            
            return `
                <div class="taxonomy-option" data-tag-id="${tag.id}" data-tag-label="${escapedLabel}">
                    <div class="flex justify-between items-center">
                        <span class="font-medium text-gray-900">${tag.label}</span>
                        <span class="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">${tag.id}</span>
                    </div>
                </div>
            `;
        }).join('');
        
        dropdown.innerHTML = dropdownHTML;
        dropdown.classList.remove('hidden');
        
        // Add click handlers to options
        const options = dropdown.querySelectorAll('.taxonomy-option');
        options.forEach(option => {
            option.addEventListener('click', (e) => {
                e.stopPropagation();
                const tagId = option.dataset.tagId;
                const tagLabel = option.dataset.tagLabel;
                const itemId = inputElement.closest('.form-row')?.dataset?.itemId;
                
                if (tagId && tagLabel && itemId) {
                    this.selectTag(parseInt(tagId), tagLabel, itemId, inputElement);
                }
            });
        });
    }

    /**
     * Hide dropdown
     */
    hideDropdown(inputElement) {
        const container = inputElement.parentNode;
        const dropdown = container.querySelector('.taxonomy-dropdown');
        
        if (dropdown) {
            dropdown.classList.add('hidden');
        }
    }

    /**
     * Select a taxonomy tag
     */
    selectTag(tagId, tagLabel, itemId, inputElement) {
        console.log(`Selecting tag: ${tagLabel} (ID: ${tagId}) for item ${itemId}`);
        
        // Update the input
        inputElement.value = tagLabel;
        inputElement.dataset.tagId = tagId;
        
        // Hide dropdown
        this.hideDropdown(inputElement);
        
        // Visual feedback
        inputElement.classList.add('border-green-500', 'bg-green-50');
        setTimeout(() => {
            inputElement.classList.remove('border-green-500', 'bg-green-50');
        }, 1000);
        
        // Notify callback
        if (this.onSelectCallback) {
            this.onSelectCallback(itemId, tagId, tagLabel);
        }
    }

    /**
     * Clear cache
     */
    clearCache() {
        this.searchCache.clear();
    }
}