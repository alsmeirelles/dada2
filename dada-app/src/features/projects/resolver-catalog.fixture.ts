import type { Capabilities } from '../../api/capabilities'

/** `consensus_pipelines` exactly as the API catalog describes them, for tests. */
export const consensusPipelines: Capabilities['consensus_pipelines'] = {
  "classification": {
    "id": "statistical_class_consensus",
    "version": "1.0.0",
    "unavailable_reason": null,
    "class_strategies": [
      {
        "id": "multilabel_binary_vote",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      },
      {
        "id": "dirichlet_vote",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": [
          {
            "name": "alpha",
            "kind": "number",
            "default": 0.5,
            "nullable": false,
            "options": null,
            "minimum": 0.1,
            "maximum": 10,
            "minimum_inclusive": true,
            "maximum_inclusive": true,
            "advanced": true,
            "unit": null,
            "help": "Prior count per outcome; 0.5 is the Jeffreys prior."
          },
          {
            "name": "minimum_posterior",
            "kind": "number",
            "default": 0.9,
            "nullable": false,
            "options": null,
            "minimum": 0.5,
            "maximum": 0.999,
            "minimum_inclusive": true,
            "maximum_inclusive": true,
            "advanced": false,
            "unit": null,
            "help": "Probability the selected outcome must have of being the most likely one."
          }
        ]
      },
      {
        "id": "reliability_weighted_vote",
        "version": "1.0.0",
        "conditional": true,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      },
      {
        "id": "dawid_skene",
        "version": "1.0.0",
        "conditional": true,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      }
    ],
    "geometry_strategies": [],
    "parameters": [],
    "review_thresholds": [
      {
        "name": "minimum_support",
        "kind": "ratio",
        "default": {
          "numerator": 2,
          "denominator": 3
        },
        "nullable": false,
        "options": null,
        "minimum": {
          "numerator": 1,
          "denominator": 2
        },
        "maximum": {
          "numerator": 1,
          "denominator": 1
        },
        "minimum_inclusive": false,
        "maximum_inclusive": true,
        "advanced": false,
        "unit": null,
        "help": "Share of valid votes the winning outcome needs; it must exceed one half."
      }
    ]
  },
  "detection": {
    "id": "two_stage_detection_consensus",
    "version": "1.0.0",
    "unavailable_reason": null,
    "class_strategies": [
      {
        "id": "categorical_vote",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": [
          {
            "name": "decision_rule",
            "kind": "enum",
            "default": "supermajority",
            "nullable": false,
            "options": [
              "plurality",
              "strict_majority",
              "supermajority"
            ],
            "minimum": null,
            "maximum": null,
            "minimum_inclusive": null,
            "maximum_inclusive": null,
            "advanced": false,
            "unit": null,
            "help": "How the winning outcome is chosen before the support gate."
          }
        ]
      },
      {
        "id": "dirichlet_vote",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": [
          {
            "name": "alpha",
            "kind": "number",
            "default": 0.5,
            "nullable": false,
            "options": null,
            "minimum": 0.1,
            "maximum": 10,
            "minimum_inclusive": true,
            "maximum_inclusive": true,
            "advanced": true,
            "unit": null,
            "help": "Prior count per outcome; 0.5 is the Jeffreys prior."
          },
          {
            "name": "minimum_posterior",
            "kind": "number",
            "default": 0.9,
            "nullable": false,
            "options": null,
            "minimum": 0.5,
            "maximum": 0.999,
            "minimum_inclusive": true,
            "maximum_inclusive": true,
            "advanced": false,
            "unit": null,
            "help": "Probability the selected outcome must have of being the most likely one."
          }
        ]
      },
      {
        "id": "reliability_weighted_vote",
        "version": "1.0.0",
        "conditional": true,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      },
      {
        "id": "dawid_skene",
        "version": "1.0.0",
        "conditional": true,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      }
    ],
    "geometry_strategies": [
      {
        "id": "coordinate_median",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      },
      {
        "id": "trimmed_mean_box",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": [
          {
            "name": "trim_fraction",
            "kind": "number",
            "default": 0.2,
            "nullable": false,
            "options": null,
            "minimum": 0,
            "maximum": 0.4,
            "minimum_inclusive": true,
            "maximum_inclusive": true,
            "advanced": false,
            "unit": null,
            "help": "Share of boxes trimmed from each end of every coordinate."
          }
        ]
      },
      {
        "id": "weighted_box_fusion",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      }
    ],
    "parameters": [
      {
        "name": "matching_iou",
        "kind": "number",
        "default": 0.5,
        "nullable": false,
        "options": null,
        "minimum": 0,
        "maximum": 1,
        "minimum_inclusive": false,
        "maximum_inclusive": true,
        "advanced": false,
        "unit": null,
        "help": "Minimum IoU for two raters' boxes to describe one object."
      }
    ],
    "review_thresholds": [
      {
        "name": "minimum_support",
        "kind": "ratio",
        "default": {
          "numerator": 2,
          "denominator": 3
        },
        "nullable": false,
        "options": null,
        "minimum": {
          "numerator": 1,
          "denominator": 2
        },
        "maximum": {
          "numerator": 1,
          "denominator": 1
        },
        "minimum_inclusive": false,
        "maximum_inclusive": true,
        "advanced": false,
        "unit": null,
        "help": "Share of valid votes the winning outcome needs; it must exceed one half."
      },
      {
        "name": "minimum_median_iou",
        "kind": "number",
        "default": 0.5,
        "nullable": false,
        "options": null,
        "minimum": 0,
        "maximum": 1,
        "minimum_inclusive": false,
        "maximum_inclusive": true,
        "advanced": false,
        "unit": null,
        "help": "Minimum median pairwise IoU of an accepted object's boxes."
      }
    ]
  },
  "segmentation": {
    "id": "two_stage_segmentation_consensus",
    "version": "1.0.0",
    "unavailable_reason": null,
    "class_strategies": [
      {
        "id": "categorical_vote",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": [
          {
            "name": "decision_rule",
            "kind": "enum",
            "default": "supermajority",
            "nullable": false,
            "options": [
              "plurality",
              "strict_majority",
              "supermajority"
            ],
            "minimum": null,
            "maximum": null,
            "minimum_inclusive": null,
            "maximum_inclusive": null,
            "advanced": false,
            "unit": null,
            "help": "How the winning outcome is chosen before the support gate."
          }
        ]
      },
      {
        "id": "dirichlet_vote",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": [
          {
            "name": "alpha",
            "kind": "number",
            "default": 0.5,
            "nullable": false,
            "options": null,
            "minimum": 0.1,
            "maximum": 10,
            "minimum_inclusive": true,
            "maximum_inclusive": true,
            "advanced": true,
            "unit": null,
            "help": "Prior count per outcome; 0.5 is the Jeffreys prior."
          },
          {
            "name": "minimum_posterior",
            "kind": "number",
            "default": 0.9,
            "nullable": false,
            "options": null,
            "minimum": 0.5,
            "maximum": 0.999,
            "minimum_inclusive": true,
            "maximum_inclusive": true,
            "advanced": false,
            "unit": null,
            "help": "Probability the selected outcome must have of being the most likely one."
          }
        ]
      },
      {
        "id": "reliability_weighted_vote",
        "version": "1.0.0",
        "conditional": true,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      },
      {
        "id": "dawid_skene",
        "version": "1.0.0",
        "conditional": true,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1"
        },
        "parameters": []
      }
    ],
    "geometry_strategies": [
      {
        "id": "segmentation_majority_vote",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1",
          "opencv-python-headless": "4.13.0.92",
          "pandas": "3.0.6",
          "crowd-kit": "1.4.2"
        },
        "parameters": []
      },
      {
        "id": "segmentation_em",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1",
          "opencv-python-headless": "4.13.0.92",
          "pandas": "3.0.6",
          "crowd-kit": "1.4.2"
        },
        "parameters": []
      },
      {
        "id": "segmentation_rasa",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1",
          "opencv-python-headless": "4.13.0.92",
          "pandas": "3.0.6",
          "crowd-kit": "1.4.2"
        },
        "parameters": []
      },
      {
        "id": "staple",
        "version": "1.0.0",
        "conditional": false,
        "unavailable_reason": null,
        "dependencies": {
          "numpy": "2.4.6",
          "scipy": "1.17.1",
          "opencv-python-headless": "4.13.0.92"
        },
        "parameters": [
          {
            "name": "pixel_threshold",
            "kind": "number",
            "default": 0.5,
            "nullable": false,
            "options": null,
            "minimum": 0,
            "maximum": 1,
            "minimum_inclusive": false,
            "maximum_inclusive": false,
            "advanced": false,
            "unit": null,
            "help": "Posterior probability at which a pixel joins the mask."
          }
        ]
      }
    ],
    "parameters": [
      {
        "name": "matching_metric",
        "kind": "enum",
        "default": "iou",
        "nullable": false,
        "options": [
          "iou",
          "dice"
        ],
        "minimum": null,
        "maximum": null,
        "minimum_inclusive": null,
        "maximum_inclusive": null,
        "advanced": false,
        "unit": null,
        "help": "Overlap measure used to match masks and to gate their agreement."
      },
      {
        "name": "matching_threshold",
        "kind": "number",
        "default": 0.5,
        "nullable": false,
        "options": null,
        "minimum": 0,
        "maximum": 1,
        "minimum_inclusive": false,
        "maximum_inclusive": true,
        "advanced": false,
        "unit": null,
        "help": "Minimum overlap for two raters' masks to describe one instance."
      },
      {
        "name": "post_processing.remove_components_below",
        "kind": "area",
        "default": null,
        "nullable": true,
        "options": null,
        "minimum": null,
        "maximum": null,
        "minimum_inclusive": null,
        "maximum_inclusive": null,
        "advanced": true,
        "unit": null,
        "help": "Remove disconnected components smaller than this area."
      },
      {
        "name": "post_processing.fill_holes_below",
        "kind": "area",
        "default": null,
        "nullable": true,
        "options": null,
        "minimum": null,
        "maximum": null,
        "minimum_inclusive": null,
        "maximum_inclusive": null,
        "advanced": true,
        "unit": null,
        "help": "Fill holes smaller than this area."
      },
      {
        "name": "post_processing.simplify_tolerance",
        "kind": "number",
        "default": null,
        "nullable": true,
        "options": null,
        "minimum": 0,
        "maximum": 10,
        "minimum_inclusive": false,
        "maximum_inclusive": true,
        "advanced": true,
        "unit": "px",
        "help": "Polygon simplification tolerance."
      }
    ],
    "review_thresholds": [
      {
        "name": "minimum_support",
        "kind": "ratio",
        "default": {
          "numerator": 2,
          "denominator": 3
        },
        "nullable": false,
        "options": null,
        "minimum": {
          "numerator": 1,
          "denominator": 2
        },
        "maximum": {
          "numerator": 1,
          "denominator": 1
        },
        "minimum_inclusive": false,
        "maximum_inclusive": true,
        "advanced": false,
        "unit": null,
        "help": "Share of valid votes the winning outcome needs; it must exceed one half."
      },
      {
        "name": "minimum_median_overlap",
        "kind": "number",
        "default": 0.5,
        "nullable": false,
        "options": null,
        "minimum": 0,
        "maximum": 1,
        "minimum_inclusive": false,
        "maximum_inclusive": true,
        "advanced": false,
        "unit": null,
        "help": "Minimum median pairwise overlap, in the matching metric, of an accepted instance's masks."
      }
    ]
  }
}
