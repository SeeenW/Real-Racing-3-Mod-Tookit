//
//  depth_of_field.fsh
//
//  Created by bend on 06/09/13.
//  Copyright EA 2013. All rights reserved.
//

#define REDUCE_HALO_WITH_PRE_MULT
//#define REDUCE_HALO_WITH_WEIGHTS

uniform lowp sampler2D s_Texture0;		// Screen texture
uniform lowp sampler2D s_Texture1;		// Depth texture
uniform lowp sampler2D s_Texture2;		// Half size CoC texture
uniform lowp sampler2D s_Texture3;		// Half size vertical blur texture

varying lowp vec2 v_TexCoord0;

#if defined(PASS_1_WRITE_COC)

	// Clip info
	uniform highp float u_NearFocusPlane;
	uniform highp float u_FarFocusPlane;
	uniform highp float u_NearFocusFalloffInv;
	uniform highp float u_FarFocusFalloffInv;

	uniform highp float u_Proj_33;
	uniform highp float u_Proj_34_Negative;

	// Calculate the circle of confusion from a depth texture value.
	// The paper "Accurate Depth of Field Simulation in Real Time" describes how
	// the depth value is derived: http://www.cg.tuwien.ac.at/~ginko/v26i1pp015-023.pdf
	lowp float calculate_CoC( highp float depth )
	{
		// Calculate the circle of confusion
		highp float z = u_Proj_34_Negative / (depth + u_Proj_33);		// Get the depth in world coords

		highp float nearCoC = (z - u_NearFocusPlane) * u_NearFocusFalloffInv;
		highp float farCoC = (z - u_FarFocusPlane) * u_FarFocusFalloffInv;

		return clamp( max( nearCoC, farCoC ), 0.0, 1.0 );
	}
	
	void main()
	{
		lowp vec3 colour = texture2D( s_Texture0, v_TexCoord0 ).rgb;
		highp float depth = texture2D( s_Texture1, v_TexCoord0 ).r;
		highp float coc = calculate_CoC( depth );

		#if defined(REDUCE_HALO_WITH_PRE_MULT)
			gl_FragColor = vec4( colour * coc, coc );
		#else
			gl_FragColor = vec4( colour, coc );
		#endif
	}

#endif // PASS_1_WRITE_COC

#if defined(PASS_2_VERTICAL_BLUR) || defined(PASS_3_HORIZONTAL_BLUR)

	#ifdef REDUCE_HALO_WITH_WEIGHTS
		void weightedBlur( inout highp vec3 colour,
						   inout highp float totalWeight,
						   in highp float bleedBias,
						   in highp float bleedMult,
						   in highp float centerDepth,
						   in highp float centerCoC,
						   in highp float sampleDepth,
						   in highp float sampleCoC,
						   in highp vec3 sampleColour )
		{
			highp float weight = (sampleDepth < centerDepth) ? (sampleCoC * bleedMult) : 1.0;
			weight = (centerCoC > (sampleCoC + bleedBias)) ? weight : 1.0;
			weight = clamp( weight, 0.0, 1.0 );
			colour += sampleColour * weight;
			totalWeight += weight;
		}
	#endif

	#if defined(PASS_2_VERTICAL_BLUR)
		#define TEXTURE s_Texture2
	#else
		#define TEXTURE s_Texture3
	#endif

	varying lowp vec2 v_TexCoord1;
	varying lowp vec2 v_TexCoord2;
	//varying lowp vec2 v_TexCoord3;
	//varying lowp vec2 v_TexCoord4;

	void main()
	{
		lowp vec4 colour0 = texture2D( TEXTURE, v_TexCoord0 );
		lowp vec4 colour1 = texture2D( TEXTURE, v_TexCoord1 );
		lowp vec4 colour2 = texture2D( TEXTURE, v_TexCoord2 );
		//lowp vec4 colour3 = texture2D( TEXTURE, v_TexCoord3 );
		//lowp vec4 colour4 = texture2D( TEXTURE, v_TexCoord4 );

		#if defined(REDUCE_HALO_WITH_PRE_MULT)
			//const lowp float weight0 = 0.1111111112;
			//const lowp float weight1 = 0.2222222222;
			//const lowp float weight2 = 0.2222222222;
			const lowp float weight0 = 0.2;
			const lowp float weight1 = 0.4;
			lowp vec4 colour = (colour0 * weight0) +
							   (colour1 * weight1) +
							   (colour2 * weight1);// +
							   //(colour3 * weight2) +
							   //(colour4 * weight2);
			gl_FragColor = colour;
		#elif defined(REDUCE_HALO_WITH_WEIGHTS)

			const highp float bleedBias = 0.0;
			const highp float bleedMult = 3.0;
			highp float centerDepth = texture2D( s_Texture1, v_TexCoord0 );

			highp vec3 colour = vec3( 0.0 );
			highp float totalWeight = 0.0;

			weightedBlur( colour, totalWeight, bleedBias, bleedMult, centerDepth, colour0.a, centerDepth, colour0.a, colour0.rgb );
			weightedBlur( colour, totalWeight, bleedBias, bleedMult, centerDepth, colour0.a, texture2D( s_Texture1, v_TexCoord1 ), colour1.a, colour1.rgb );
			weightedBlur( colour, totalWeight, bleedBias, bleedMult, centerDepth, colour0.a, texture2D( s_Texture1, v_TexCoord2 ), colour2.a, colour2.rgb );
			//weightedBlur( colour, totalWeight, bleedBias, bleedMult, centerDepth, colour0.a, texture2D( s_Texture1, v_TexCoord3 ), colour3.a, colour3.rgb );
			//weightedBlur( colour, totalWeight, bleedBias, bleedMult, centerDepth, colour0.a, texture2D( s_Texture1, v_TexCoord4 ), colour4.a, colour4.rgb );

			colour /= totalWeight;

			gl_FragColor = vec4( colour, colour0.a );
		#else
			//const lowp float weight0 = 0.1111111112;
			//const lowp float weight1 = 0.2222222222;
			//const lowp float weight2 = 0.2222222222;
			const lowp float weight0 = 0.2;
			const lowp float weight1 = 0.4;
			lowp vec3 colour = (colour0.rgb * weight0) +
							   (colour1.rgb * weight1) +
							   (colour2.rgb * weight1);// +
							   //(colour3.rgb * weight2) +
							   //(colour4.rgb * weight2);
			gl_FragColor = vec4( colour, colour0.a );
		#endif
	}

#endif // PASS_2_VERTICAL_BLUR || PASS_3_HORIZONTAL_BLUR

#if defined(PASS_4_COMPOSIT)

	void main()
	{
		lowp vec3 colour = texture2D( s_Texture0, v_TexCoord0 ).rgb;
		lowp vec4 blur = texture2D( s_Texture2, v_TexCoord0 );

		#if defined(DEBUG_COC)
			gl_FragColor = vec4( vec3( blur.a ), 1.0 );
		#elif defined(DEBUG_BLUR)
			gl_FragColor = vec4( blur.rgb, 1.0 );
		#else
			#if defined(REDUCE_HALO_WITH_PRE_MULT)
				gl_FragColor = vec4( (colour * (1.0 - blur.a)) + blur.rgb, 1.0 );
			#else
				gl_FragColor = vec4( mix( colour, blur.rgb, blur.a ), 1.0 );
			#endif
		#endif
		
		//gl_FragColor = vec4( (colour * (1.0 - blur.a)) + (blur.rgb * blur.a), 1.0 );
		//gl_FragColor = vec4( (colour * (1.0 - blur.a)) + blur.rgb, 1.0 );
		//gl_FragColor = vec4( (1.0 - blur.a) * colour + blur.rgb, 1.0 );
		//gl_FragColor = vec4( blur.rgb, 1.0 );
		//gl_FragColor = vec4( colour, 1.0 );
	}

#endif // PASS_4_COMPOSIT

